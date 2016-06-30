from influxdb import InfluxDBClient

service_to_track = ('compute', 'image', 'network', 'volume')
client = InfluxDBClient('172.18.160.72', 8086, database='endpoints')
#res = client.query('select count(value) from services;')
total_srv = client.query('select count(value) from service_response group by service_name;')
bad_srv = client.query('select count(value) from service_response where status_code <> 200'
                       ' and status_code <> 300 group by service_name;')

for service in service_to_track:
    key = ('service_response', {'service_name': service})
    try:
        value = total_srv[key].next()
        total_uptime = value['count']
    except:
        print "There's no records for service", service
        continue

    try:
        value = bad_srv[key].next()
        srv_downtime = value['count']
    except:
        srv_downtime = 0

    print ("Service %s was down approximately %d seconds which are %.1f"
           "%% of total uptime" %
           (service, srv_downtime, (100.0 * srv_downtime) / total_uptime))

tags_resp = client.query('show tag values from floating_ip_pings with key=address;')
addresses = [item['value'] for item in tags_resp[(u'floating_ip_pings', None)]]
total_ping = client.query('select count(value) from floating_ip_pings group by address;')
bad_ping_exit_code = client.query('select count(value) from floating_ip_pings where exit_code <> 0'
                       'group by address;')
partially_lost_ping = client.query('select sum(value) from floating_ip_pings where exit_code = 0'
                       'group by address;')

for address in addresses:
    key = ('floating_ip_pings', {'address': address})
    try:
        value = total_ping[key].next()
        total_time = value['count']
    except:
        print "There's no records about address", address
        continue

    try:
        value =  bad_ping_exit_code[key].next()
        failed_ping = value['count']
    except:
        failed_ping = 0

    try:
        value = partially_lost_ping[key].next()
        lost_ping = value['sum'] * 0.05
    except:
        lost_ping = 0

    failed = failed_ping + lost_ping

    print ("Address %s was unreachable approximately %.1f second which are %.1f"
           "%% of total uptime" %
            (address, failed, (100.0 * failed) / total_time))

