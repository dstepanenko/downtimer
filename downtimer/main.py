from urlparse import urlparse
import logging
import threading
import time

from keystoneauth1 import session
from keystoneclient.v3 import client as keystone_client
from keystoneauth1.identity import Password
from neutronclient.v2_0 import client as neutron_client

from daemonize import Daemonize

from config import CONF
from db_adapters import InfluxDBAdapter, SQLDBAdapter
import utils

logger = logging.getLogger(__name__)
adapters = {'influx': InfluxDBAdapter, 'sql': SQLDBAdapter}


class Downtimer(object):
    def __init__(self):
        self.conf = CONF
        self.db_adapter = adapters[self.conf.db_adapter](self.conf)
        self.threads = []

    def run(self):
        try:
            method_name = 'handle_' + self.conf.mode
            getattr(self, method_name)()

            while True:
                time.sleep(3)

        except(AttributeError):
            raise AttributeError(
                'Unrecognized platform type %s specified in config file' %
                self.conf.platform)

    def handle_static(self):
        for ip in self.conf.ips:
            self.add_worker(utils.ping, (ip, self.db_adapter))

    def handle_openstack(self):
        auth = Password(auth_url=self.conf.auth_url,
                        username=self.conf.user, password=self.conf.password,
                        project_name="admin", user_domain_id="default",
                        project_domain_id="default")
        sess = session.Session(auth=auth)
        keystone = keystone_client.Client(session=sess)
        for service in keystone.services.list():
            endpoint = keystone.endpoints.find(service_id=service.id,
                                               interface='public')
            url = urlparse(endpoint.url)
            new_url = '{0}://{1}'.format(url.scheme, url.netloc)
            self.add_worker(utils.do_check,
                            (service.name, new_url, self.db_adapter))

        neutron = neutron_client.Client(session=sess)
        for fip in neutron.list_floatingips()['floatingips']:
            if fip['status'] == 'ACTIVE':
                self.add_worker(utils.ping,
                                (fip['floating_ip_address'], self.db_adapter))

    def add_worker(self, target, args):
        worker = threading.Thread(target=target,
                                  args=args)
        worker.daemon = True
        worker.start()
        self.threads.append(worker)

    def report(self):
        with open(self.conf.report_file, "w") as f:
            for service in self.db_adapter.get_service_statuses():
                f.write("Service %s was down approximately %d seconds out of "
                        "%d seconds which amounting %.1f%% of total uptime\n" %
                        (service['service'], service['srv_downtime'],
                         service['total_uptime'],
                         (100.0 * service['srv_downtime']) /
                         service['total_uptime']))

            for instance in self.db_adapter.get_instance_statuses():
                f.write(
                    "Address %s was unreachable approximately %.1f second of "
                    "%d seconds which amounting %.1f %% of total uptime\n" %
                    (instance['address'],
                     instance['lost_pkts'],
                     instance['attempts'],
                     (instance['lost_pkts'] * 1e2) / instance['attempts']))


def downtimer_starter():
    downtimer_app = Downtimer()
    downtimer_app.run()


def main(argv=None):

    logger.setLevel(CONF.log_level)
    formatter = logging.Formatter(CONF.log_format)
    handler = logging.FileHandler(CONF.log_file)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    daemon = Daemonize(app="Downtimer",
                       pid=CONF.pid_file,
                       action=downtimer_starter,
                       logger=logger,
                       keep_fds=[handler.stream.fileno()])
    daemon.start()

if __name__ == "__main__":
    downtimer_starter()
