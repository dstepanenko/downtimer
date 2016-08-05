import ConfigParser
import logging
import re
import requests
import subprocess
import time
import threading

from daemon import runner
from datetime import datetime
from influxdb import InfluxDBClient
from keystoneauth1 import session
from keystoneclient.v3 import client as keystone_client
from keystoneauth1.identity import Password
from neutronclient.v2_0 import client as neutron_client
from urlparse import urlparse

SERVICE_TIMEOUT = 0.9
CONFIG_FILE = "/etc/downtimer/conf.ini"

class Daemon(runner.DaemonRunner):
    def _start(self):
        super(Daemon, self)._start()

    def _stop(self):
        self._report()
        super(Daemon, self)._stop()

    def _restart(self):
        super(Daemon, self)._restart()

    def _report(self):
        self.app.report()

    action_funcs = {
        'start': _start,
        'stop': _stop,
        'restart': _restart,
        'report': _report
        }


class Config:
    def __init__(self, file_name):
        conf = ConfigParser.ConfigParser()
        conf.read(CONFIG_FILE)

        self.auth_url = conf.get('global', 'keystone_endpoint')
        self.os_user = conf.get('global', 'user')
        self.os_pass = conf.get('global', 'password')
        self.report_file = conf.get('global', 'report_file')

        self.db_host = conf.get('db', 'host')
        self.db_port = conf.get('db', 'port')


class Downtimer:
    def __init__(self, conf_file='conf.ini'):
        #  All these paths should be defined for using python-daemon runner
        self.stdin_path = '/dev/null'
        self.stdout_path = '/var/log/downtimer_output'
        self.stderr_path = '/dev/tty'
        self.pidfile_path =  '/var/run/downtimer.pid'
        self.pidfile_timeout = 5
        self.conf = Config(conf_file)
        self.db_url = 'http://{host}:{port}/write?db=endpoints'.format(
            host=self.conf.db_host,
            port=self.conf.db_port
        )
        self.threads = []

    def run(self):
        auth = Password(auth_url=self.conf.auth_url, username=self.conf.os_user,
                        password=self.conf.os_pass, project_name="admin",
                        user_domain_id="default", project_domain_id="default")
        sess = session.Session(auth=auth)
        keystone = keystone_client.Client(session=sess)
        for service in keystone.services.list():
            endpoint = keystone.endpoints.find(service_id=service.id,
                                               interface='public')
            url = urlparse(endpoint.url)
            new_url = "http://" + url.hostname + ":" + str(url.port) + "/"
            self.add_worker(do_check, (service.name, new_url, self.db_url))

        neutron = neutron_client.Client(session=sess)
        for fip in neutron.list_floatingips()['floatingips']:
            if fip['status'] == 'ACTIVE':
                self.add_worker(ping, (fip['floating_ip_address'], self.db_url))

        while True:
            time.sleep(3)

    def add_worker(self, target, args):
        worker = threading.Thread(target=target,
                                  args=args)
        worker.daemon = True
        worker.start()
        self.threads.append(worker)

    def report(self):
        #  TODO for 2 methods we're using different way to access influx db
        #  this is not critical, because we're going to move to sql db soon
        client = InfluxDBClient(self.conf.db_host, self.conf.db_port,
                                database='endpoints')
        #res = client.query('select count(value) from services;')
        services_ref = client.query('show tag values from service_response '
                                        'with key = service_name')
        service_to_track = [x['value'] for x in services_ref[('service_response', None)]]

        total_srv = client.query('select count(value) from service_response '
                                 'group by service_name;')
        bad_srv = client.query('select count(value) from service_response where '
                               'status_code <> 200 and status_code <> 300 '
                               'group by service_name;')

        with open(self.conf.report_file, "w") as f:
            for service in service_to_track:
                key = ('service_response', {'service_name': service})
                try:
                    value = total_srv[key].next()
                    total_uptime = value['count']
                except:
                    f.write("There's no records for service %s\n" % service)
                    continue

                try:
                    value = bad_srv[key].next()
                    srv_downtime = value['count']
                except:
                    srv_downtime = 0

                f.write("Service %s was down approximately %d seconds which is"
                        " %.1f%% of total uptime\n" %
                        (service, srv_downtime,
                        (100.0 * srv_downtime) / total_uptime))

            tags_resp = client.query('show tag values from floating_ip_pings '
                                     'with key=address;')
            addresses = [item['value'] for item in tags_resp[(u'floating_ip_pings', None)]]
            total_ping = client.query('select count(value) from floating_ip_pings '
                                      'group by address;')
            bad_ping_exit_code = client.query('select count(value) from floating_ip_pings '
                                              'where exit_code <> 0 group by address;')
            partially_lost_ping = client.query('select sum(value) from floating_ip_pings '
                                               'where exit_code = 0 group by address;')

            for address in addresses:
                key = ('floating_ip_pings', {'address': address})
                try:
                    value = total_ping[key].next()
                    total_time = value['count']
                except:
                    f.write("There's no records about address %s\n" % address)
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

                f.write("Address %s was unreachable approximately %.1f second "
                        "which is %.1f%% of total uptime\n" %
                        (address, failed, (100.0 * failed) / total_time))


def do_check(endpoint, address, db_url):
    while True:
        try:
            timeout = 0
            r = requests.get(address, timeout=SERVICE_TIMEOUT)
            status_msg = 'FAIL'
            if r.status_code in [200, 300]:
                status_msg = 'OK'
            print (endpoint + " " + address + ": " + str(r.status_code) + " "
                   + status_msg + " " + str(datetime.now()) + "\n")
            wait_time = 1 - r.elapsed.microseconds / 1000000.0
        except Exception as e:
            timeout = 1
            wait_time = 1 - SERVICE_TIMEOUT
            print e

        message = ('service_response,service_name=' + endpoint +
            ',address=' + address +
            ' status_code=' + str(r.status_code) + ',timeout=' +
            str(timeout) + ',value=' + str(r.elapsed.microseconds))
        influx_resp = requests.post(
            db_url,
            message)
        print "Influx: " + str(influx_resp.status_code) + "\n"
        time.sleep(wait_time)
    
    
def ping(address, db_url):
    while True:
        try:
            response = subprocess.check_output(
                ['ping', '-i', '0.2', '-c', '5', address],
                stderr=subprocess.STDOUT,  # get all output
                universal_newlines=True  # return string not bytes
            )
            lost = re.search('\d+(?=\% packet loss,)', response)
            packet_loss = lost.group(0)
            total = re.search('(?<=loss, time )\d+', response)
            total_time = total.group(0)
            exit_code = '0'
        except:
            exit_code = '1'
            packet_loss = '100'
            total_time = '2000'
        print 'ttt = %s loss = %s code = %s' % (total_time, packet_loss, exit_code)
        message = ('floating_ip_pings,address=' + address + ' total_time=' + total_time +
                   ',exit_code=' + exit_code + ',value=' + packet_loss)
        influx_resp = requests.post(
            db_url,
            message)
        print "Influx: " + str(influx_resp.status_code) + "\n"


logger = logging.getLogger("Downtimer")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler = logging.FileHandler("/var/log/downtimer.log")
handler.setFormatter(formatter)
logger.addHandler(handler)

downtimer_app = Downtimer()
daemon_runner = Daemon(downtimer_app)
daemon_runner.daemon_context.files_preserve=[handler.stream]
daemon_runner.do_action()
