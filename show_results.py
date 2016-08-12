from db_adapters import InfluxDBAdapter
from main import Config

adapter = InfluxDBAdapter(Config('conf.ini'))

for service in adapter.get_service_statuses():
    print ("Service %s was down approximately %d seconds which are %.1f"
           "%% of total uptime" % (service['service'], service['srv_downtime'],
                                   (100.0 * service['srv_downtime']) /
                                   service['total_uptime']))

for address in adapter.get_instance_statuses():
    print ("Address %s was unreachable approximately %.1f second which are "
           "%.1f %% of total uptime" % (address['address'], address['failed'],
                                        (100.0 * address['failed']) /
                                        address['total_time']))
