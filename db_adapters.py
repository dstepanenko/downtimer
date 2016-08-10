from influxdb import InfluxDBClient
import requests
import logging


class DBAdapter(object):
    def store_instance_status(self, address, total_time, exit_code, value):
        pass

    def store_service_status(self, endpoint, address, status_code, timeout,
                             value):
        pass

    def get_instance_statuses(self):
        pass

    def get_service_statuses(self):
        pass


class InfluxDBAdapter(DBAdapter):
    def __init__(self, config):
        self.logger = logging.getLogger('InfluxDBAdapter')
        self.db_url = 'http://{host}:{port}/write?db=endpoints'.format(
            host=config.db_host,
            port=config.db_port
        )
        self.client = InfluxDBClient(config.db_host, config.db_port,
                                     database='endpoints')

    def store_instance_status(self, address, total_time, exit_code, value):
        message = ('floating_ip_pings,address=%s total_time=%s,exit_code=%s,'
                   'value=%s') % (address, total_time, exit_code, value)
        influx_resp = requests.post(self.db_url, message)
        self.logger.info(str(influx_resp.status_code))

    def store_service_status(self, endpoint, address, status_code, timeout,
                             value):
        message = ('service_response,service_name=%s,address=%s status_code=%s'
                   ',timeout=%s,value=%s') % (endpoint, address, status_code,
                                              timeout, value)
        influx_resp = requests.post(self.db_url, message)
        self.logger.info(str(influx_resp.status_code))

    def get_instance_statuses(self):
        tags_resp = self.client.query('show tag values from floating_ip_pings '
                                      'with key=address;')
        addresses = [item['value'] for item in
                     tags_resp[(u'floating_ip_pings', None)]]
        total_ping = self.client.query('select count(value) from '
                                       'floating_ip_pings group by address;')
        bad_ping_exit_code = self.client.query(
            'select count(value) from floating_ip_pings '
            'where exit_code <> 0 group by address;')
        partially_lost_ping = self.client.query(
            'select sum(value) from floating_ip_pings '
            'where exit_code = 0 group by address;')

        statuses = []

        for address in addresses:
            key = ('floating_ip_pings', {'address': address})
            try:
                value = total_ping[key].next()
                total_time = value['count']
            except:
                self.logger.warn("There's no records about address", address)
                continue

            try:
                value = bad_ping_exit_code[key].next()
                failed_ping = value['count']
            except:
                failed_ping = 0

            try:
                value = partially_lost_ping[key].next()
                lost_ping = value['sum'] * 0.05
            except:
                lost_ping = 0

            failed = failed_ping + lost_ping

            statuses.append({'address': address, 'failed': failed,
                             'total_time': total_time})

        return statuses

    def get_service_statuses(self):
        services_ref = self.client.query('show tag values from '
                                         'service_response '
                                         'with key = service_name')
        service_to_track = [x['value'] for x in
                            services_ref[('service_response', None)]]

        total_srv = self.client.query('select count(value) from '
                                      'service_response '
                                      'group by service_name;')
        bad_srv = self.client.query(
            'select count(value) from service_response where '
            'status_code <> 200 and status_code <> 300 '
            'group by service_name;')

        services = []

        for service in service_to_track:
            key = ('service_response', {'service_name': service})
            try:
                value = total_srv[key].next()
                total_uptime = value['count']
            except:
                self.logger.warn("There's no records for service", service)
                continue

            try:
                value = bad_srv[key].next()
                srv_downtime = value['count']
            except:
                srv_downtime = 0

            services.append({'service':service, 'srv_downtime':srv_downtime,
                             'total_uptime':total_uptime})

        return services
