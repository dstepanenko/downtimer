import ConfigParser
import socket

CONFIG_FILE = "/etc/downtimer/conf.ini"


class Config(object):
    def __init__(self, file_name):
        conf = ConfigParser.SafeConfigParser()
        conf.read(file_name)

        self.log_level = conf.get('DEFAULT', 'log_level')
        self.log_file = conf.get('DEFAULT', 'log_file')
        self.pid_file = conf.get('DEFAULT', 'pid_file')
        self.log_format = conf.get('DEFAULT', 'log_format')
        self.report_file = conf.get('DEFAULT', 'report_file')

        self.mode = conf.get('global', 'mode')

        if self.mode == 'static':
            ips_str = conf.get('static', 'ips')
            if not ips_str:
                raise AttributeError('Option ips is epmty')

            self.ips = ips_str.split(',')
            for ip in self.ips:
                try:
                    socket.inet_aton(ip)
                except socket.error:
                    raise AttributeError('Illegal ip address %s passed '
                                         'to ips option in config file' % ip)

        elif self.mode == 'openstack':
            self.auth_url = conf.get('openstack', 'endpoint')
            self.user = conf.get('openstack', 'user')
            self.password = conf.get('openstack', 'password')

        self.db_adapter = conf.get('database', 'adapter')
        self.db_host = conf.get('database', 'host')

        if self.db_adapter == 'influx':
            self.db_port = conf.get('influxdb', 'port')
            try:
                true_vars = [True, '1', 'True', 'true']
                self.use_udp = conf.get('influxdb', 'use_udp') in true_vars
            except Exception:
                self.use_udp = False
            try:
                self.udp_port = int(conf.get('influxdb', 'udp_port'))
            except Exception:
                # 4444 is a default udp port for InfluxDBClient
                self.udp_port = 4444
        # Set the database name
        try:
            self.db_name = conf.get('influxdb', 'name')
        except ConfigParser.NoOptionError:
            self.db_name = 'endpoints'

CONF = Config(CONFIG_FILE)
