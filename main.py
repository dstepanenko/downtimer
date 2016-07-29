import ConfigParser
import logging
import re
import requests
import subprocess
import time
import threading

from daemon import runner
from datetime import datetime
from keystoneauth1 import session
from keystoneclient.v3 import client as keystone_client
from keystoneauth1.identity import Password
from neutronclient.v2_0 import client as neutron_client
from urlparse import urlparse

SERVICE_TIMEOUT = 0.9


class Config:
    def __init__(self, file_name):
        conf = ConfigParser.ConfigParser()
        conf.read("conf.ini")

        self.auth_url = conf.get('global', 'keystone_endpoint')
        self.os_user = conf.get('global', 'user')
        self.os_pass = conf.get('global', 'password')

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
daemon_runner = runner.DaemonRunner(downtimer_app)
daemon_runner.daemon_context.files_preserve=[handler.stream]
daemon_runner.do_action()
