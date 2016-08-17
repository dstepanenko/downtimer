from influxdb import InfluxDBClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, Service, Instance
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
            'select sum(value) from floating_ip_pings '
            'where exit_code <> 0 group by address;')
        partially_lost_ping = self.client.query(
            'select sum(value) from floating_ip_pings '
            'where exit_code = 0 group by address;')

        statuses = []

        for address in addresses:
            key = ('floating_ip_pings', {'address': address})
            try:
                value = total_ping[key].next()
                pkts_total = value['count']
            except:
                self.logger.warn("There's no records about address", address)
                continue

            try:
                value = bad_ping_exit_code[key].next()
                failed_ping = value['sum']
            except:
                failed_ping = 0

            try:
                value = partially_lost_ping[key].next()
                lost_ping = value['sum']
            except:
                lost_ping = 0

            failed = (failed_ping + lost_ping) / 100.0

            statuses.append({'address': address, 'lost_pkts': failed,
                             'attempts': pkts_total})

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


class SQLDBAdapter(DBAdapter):
    def __init__(self, config):
        self.logger = logging.getLogger('SQLDBAdapter')
        self.engine = create_engine(config.db_host)
        Base.metadata.bind = self.engine
        self.DBSession = sessionmaker()
        self.DBSession.bind = self.engine

    def store_instance_status(self, address, total_time, exit_code,
                              packet_loss):
        instance = Instance(address=address,
                            total_time=total_time,
                            exit_code=exit_code,
                            packet_loss=packet_loss)
        session = self.DBSession()
        session.add(instance)
        session.commit()

    def store_service_status(self, endpoint, address, status_code, timeout,
                             elapsed_time):
        service = Service(endpoint=endpoint,
                          address=address,
                          status_code=status_code,
                          timeout=timeout,
                          elapsed_time=elapsed_time)
        session = self.DBSession()
        session.add(service)
        session.commit()

    def get_instance_statuses(self):
        session = self.DBSession()
        instance_data = session.query(Instance).all()
        data = {}
        for instance in instance_data:
            if instance.address in data:
                record = data[instance.address]
                record['lost_pkts'] += instance.packet_loss / 100.0
                record['attempts'] += 1
            else:
                data[instance.address] = {'address': instance.address,
                                          'lost_pkts': instance.packet_loss / 100.0,
                                          'attempts': 1}
        return list(data.values())

    def get_service_statuses(self):
        session = self.DBSession()
        service_data = session.query(Service).all()
        data = {}
        for service in service_data:
            if service.endpoint in data:
                record = data[service.endpoint]
                if service.status_code not in (200, 300):
                    record['srv_downtime'] += 1
                record['total_uptime'] += 1
            else:
                srv_downtime = 0 if service.status_code in (200, 300) else 1
                data[service.endpoint] = {'service': service.endpoint,
                                          'srv_downtime': srv_downtime,
                                          'total_uptime': 1}
        return list(data.values())
