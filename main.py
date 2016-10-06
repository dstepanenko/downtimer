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
from db_adapters import InfluxDBAdapter, SQLDBAdapter

SERVICE_TIMEOUT = 0.9
CONFIG_FILE = "/etc/downtimer/conf.ini"
adapters = {'influx': InfluxDBAdapter, 'sql': SQLDBAdapter}


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


class Config(object):
    def __init__(self, file_name):
        conf = ConfigParser.ConfigParser()
        conf.read(file_name)

        self.auth_url = conf.get('global', 'keystone_endpoint')
        self.os_user = conf.get('global', 'user')
        self.os_pass = conf.get('global', 'password')
        self.report_file = conf.get('global', 'report_file')

        self.db_host = conf.get('db', 'host')
        self.db_port = conf.get('db', 'port')
        self.db_adapter = conf.get('db', 'adapter')


class Downtimer(object):
    def __init__(self, conf_file='conf.ini'):
        #  All these paths should be defined for using python-daemon runner
        self.stdin_path = '/dev/null'
        self.stdout_path = '/var/log/downtimer_output'
        self.stderr_path = '/dev/tty'
        self.pidfile_path = '/var/run/downtimer.pid'
        self.pidfile_timeout = 5
        self.conf = Config(conf_file)
        self.db_adapter = adapters[self.conf.db_adapter](self.conf)
        self.threads = []

    def run(self):
        auth = Password(auth_url=self.conf.auth_url,
                        username=self.conf.os_user, password=self.conf.os_pass,
                        project_name="admin", user_domain_id="default",
                        project_domain_id="default")
        sess = session.Session(auth=auth)
        keystone = keystone_client.Client(session=sess)
        for service in keystone.services.list():
            endpoint = keystone.endpoints.find(service_id=service.id,
                                               interface='public')
            url = urlparse(endpoint.url)
            new_url = "http://" + url.hostname + ":" + str(url.port) + "/"
            self.add_worker(do_check, (service.name, new_url, self.db_adapter))

        neutron = neutron_client.Client(session=sess)
        for fip in neutron.list_floatingips()['floatingips']:
            if fip['status'] == 'ACTIVE':
                self.add_worker(ping, (fip['floating_ip_address'],
                                       self.db_adapter))

        while True:
            time.sleep(3)

    def add_worker(self, target, args):
        worker = threading.Thread(target=target,
                                  args=args)
        worker.daemon = True
        worker.start()
        self.threads.append(worker)

    def report(self):
        with open(self.conf.report_file, "w") as f:
            for service in self.db_adapter.get_service_statuses():
                f.write("Service %s was down approximately %d seconds which "
                        "are %.1f%% of total uptime\n" %
                        (service['service'], service['srv_downtime'],
                         (100.0 * service['srv_downtime']) /
                         service['total_uptime']))

            for instance in self.db_adapter.get_instance_statuses():
                f.write(
                    "Address %s was unreachable approximately %.1f second "
                    "which are %.1f %% of total uptime\n" %
                    (instance['address'], instance['lost_pkts'],
                        (instance['lost_pkts'] * 1e2) / instance['attempts']))


def do_check(endpoint, address, db_adapter):
    while True:
        try:
            timeout = 0
            r = requests.get(address, timeout=SERVICE_TIMEOUT)
            status_msg = 'FAIL'
            if r.status_code in [200, 300]:
                status_msg = 'OK'
            print (endpoint + " " + address + ": " + str(r.status_code) + " "
                   + status_msg + " " + str(datetime.now()) + "\n")
            elapsed = r.elapsed.microseconds
            status_code = r.status_code
        except requests.exceptions.RequestException as e:
            timeout = 1
            elapsed = SERVICE_TIMEOUT * 1e6
            status_code = 408
            print e
        except Exception as e:
            print ("This situation should\'t have occured. Failed to check "
                   "address {} with exception {}".format(address, e.message))
            raise e

        db_adapter.store_service_status(endpoint, address, status_code,
                                        timeout, elapsed)

        wait_time = 1 - elapsed * 1e-6
        time.sleep(wait_time)


def ping(address, db_adapter):
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

        db_adapter.store_instance_status(address, total_time,
                                         exit_code, packet_loss)


def main(argv=None):
    logger = logging.getLogger("Downtimer")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler = logging.FileHandler("/var/log/downtimer.log")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    downtimer_app = Downtimer()
    daemon_runner = Daemon(downtimer_app)
    daemon_runner.daemon_context.files_preserve = [handler.stream]
    daemon_runner.do_action()


if __name__ == "__main__":
    main()
