import mock
import requests
import unittest

import db_adapters

from main import (do_check, ping, SERVICE_TIMEOUT, Downtimer)

EXCEPTION_MESSAGE = 'Exiting'


def raise_exc(*args, **kwargs):
    raise Exception(EXCEPTION_MESSAGE)


def timeout_exc(*args, **kwargs):
    raise requests.exceptions.Timeout


def fake_influx_config_get(obj, section, param):
    if param == 'adapter':
        return 'influx'
    return 'fake-{}'.format(param)


def fake_sql_config_get(obj, section, param):
    if param == 'adapter':
        return 'sql'
    return 'fake-{}'.format(param)


def fake_undefined_backend_config_get(obj, section, param):
    if param == 'adapter':
        return 'undefined'
    return 'fake-{}'.format(param)


class DowntimerTest(unittest.TestCase):

    @mock.patch('db_adapters.InfluxDBClient')
    @mock.patch('main.ConfigParser.ConfigParser.get',
                fake_influx_config_get)
    def test_init_with_influx_backend(self, fake_influx_db_client):
        downtimer = Downtimer()
        self.assertTrue(
            isinstance(downtimer.db_adapter, db_adapters.InfluxDBAdapter)
        )

    @mock.patch('db_adapters.sessionmaker')
    @mock.patch('db_adapters.create_engine')
    @mock.patch('main.ConfigParser.ConfigParser.get',
                fake_sql_config_get)
    def test_init_with_sql_backend(self,
                                   fake_create_engine, fake_sessionmaker):
        downtimer = Downtimer()
        self.assertTrue(
            isinstance(downtimer.db_adapter, db_adapters.SQLDBAdapter)
        )

    @mock.patch('main.ConfigParser.ConfigParser.get',
                fake_undefined_backend_config_get)
    def test_init_with_undefined_backend(self):
        self.assertRaises(KeyError, Downtimer())

    @mock.patch('main.neutron_client.Client')
    @mock.patch('main.keystone_client.Client')
    @mock.patch('main.Downtimer.add_worker')
    @mock.patch('db_adapters.InfluxDBClient')
    @mock.patch('main.time.sleep')
    @mock.patch('main.session')
    @mock.patch('main.Password')
    @mock.patch('main.ConfigParser.ConfigParser.get',
                fake_influx_config_get)
    def test_run(self, mock_passwd, mock_session, mock_sleep, mock_influx_db,
                 mock_add_worker, mock_keystone_client, mock_neutron_cl):
        fake_keystone_services_list = [mock.Mock(id='fake-id')]
        fake_neutron_list_ips = [
            {'floating_ip_address': 'ip1', 'status': 'ACTIVE'},
            {'floating_ip_address': 'ip2', 'status': 'fake-status'},
            {'floating_ip_address': 'ip3', 'status': 'ACTIVE'}
        ]
        fake_ips = {'floatingips': fake_neutron_list_ips}
        fake_host = '1.2.3.4'
        fake_port = '321'
        fake_keystone_ep = mock.Mock(
            url='http://{}:{}/'.format(fake_host, fake_port)
        )

        mock_sleep.side_effect = raise_exc
        fake_keystone_services = mock.Mock()
        fake_keystone_services.list.return_value = fake_keystone_services_list
        fake_keystone_endpoints = mock.Mock()
        fake_keystone_endpoints.find.return_value = fake_keystone_ep
        mock_keystone_client.return_value = mock.Mock(
            services=fake_keystone_services,
            endpoints=fake_keystone_endpoints
        )
        mock_neutron_cl.return_value = mock.Mock()
        mock_neutron_cl.return_value.list_floatingips.return_value = fake_ips
        downtimer = Downtimer()
        try:
            downtimer.run()
        except Exception as e:
            self.assertEqual(EXCEPTION_MESSAGE, e.message)
        calls = downtimer.add_worker.mock_calls
        expected_check_arg_list = []
        expected_ping_arg_list = []
        for call in calls:
            call_params_list = [y for y in call]
            func, args = call_params_list[1]
            if func.__name__ == 'do_check':
                expected_check_arg_list.append(args)
            if func.__name__ == 'ping':
                expected_ping_arg_list.append(args)
            else:
                assert(False, 'Unknown called function type')

        real_check_arg_list = []
        for service in fake_keystone_services_list:
            real_check_arg_list.append(
                (service.name, fake_keystone_ep.url, downtimer.db_adapter)
            )
        real_ping_arg_list = []
        for fip in fake_neutron_list_ips:
            if fip['status'] == 'ACTIVE':
                real_ping_arg_list.append(
                    (fip['floating_ip_address'], downtimer.db_adapter)
                )

        self.assertEqual(
            len(expected_check_arg_list), len(real_check_arg_list))
        self.assertEqual(
            set(expected_check_arg_list), set(real_check_arg_list))
        self.assertEqual(len(expected_ping_arg_list), len(real_ping_arg_list))
        self.assertEqual(set(expected_ping_arg_list), set(real_ping_arg_list))


class DowntimerPingTest(unittest.TestCase):

    @mock.patch('main.time.sleep')
    @mock.patch('main.requests.get')
    def test_do_check_positive_scenario(self,
                                        fake_requests_get, fake_time_sleep):
        endpoint = 'fake-endpoint'
        address = 'fake-address'
        status_code = 200
        adapter = mock.Mock()
        expected_timeout = 0
        elapsed = mock.Mock(microseconds=0.2 * 1e6)
        expected_wait_time = 1 - elapsed.microseconds * 1e-6
        fake_requests_get.return_value = mock.Mock(
            status_code=status_code,
            elapsed=elapsed
        )
        #  to avoid infinite loop we're using side_effect that
        #  raises Exception
        fake_time_sleep.side_effect = raise_exc
        try:
            do_check(endpoint, address, adapter)
        except Exception as e:
            self.assertEqual(EXCEPTION_MESSAGE, e.message)
        adapter.store_service_status.assert_called_with(
            endpoint, address,
            status_code, expected_timeout, elapsed.microseconds)
        args, kwargs = fake_time_sleep.call_args
        #  input parameters for function time.sleep is a float number, so
        #  we compare them with assumption of some inaccuracy
        self.assertTrue(abs(args[0] - expected_wait_time) < 1e-9)

    @mock.patch('main.requests.get')
    def test_do_check_exception_occured(self, fake_requests_get):
        endpoint = 'fake-endpoint'
        address = 'fake-address'
        adapter = mock.Mock()
        fake_requests_get.side_effect = raise_exc
        #  to avoid infinite loop we're using side_effect that
        #  raises Exception
        try:
            do_check(endpoint, address, adapter)
        except Exception as e:
            self.assertEqual(EXCEPTION_MESSAGE, e.message)
        adapter.store_service_status.assert_not_called()

    @mock.patch('main.time.sleep')
    @mock.patch('main.requests.get')
    def test_do_check_request_timeout(self,
                                      fake_requests_get, fake_time_sleep):
        endpoint = 'fake-endpoint'
        address = 'fake-address'
        status_code = 408
        adapter = mock.Mock()
        expected_timeout = 1
        elapsed = mock.Mock(microseconds=SERVICE_TIMEOUT * 1e6)
        expected_wait_time = 1 - elapsed.microseconds * 1e-6
        fake_requests_get.side_effect = timeout_exc
        #  to avoid infinite loop we're using side_effect that
        #  raises Exception
        fake_time_sleep.side_effect = raise_exc
        try:
            do_check(endpoint, address, adapter)
        except Exception as e:
            self.assertEqual(EXCEPTION_MESSAGE, e.message)
        adapter.store_service_status.assert_called_with(
            endpoint, address,
            status_code, expected_timeout, elapsed.microseconds)
        args, kwargs = fake_time_sleep.call_args
        #  input parameters for function time.sleep is a float number, so
        #  we compare them with assumption of some inaccuracy
        self.assertTrue(abs(args[0] - expected_wait_time) < 1e-9)

    @mock.patch('main.subprocess.check_output')
    def test_ping_positive_scenario(self, fake_check_output):
        address = 'fake-address'
        expected_exit_code = '0'
        expected_packet_loss = '0'
        expected_total_time = '200'
        response = 'a\nb\n {}% packet loss, time {}ms'.format(
            expected_packet_loss, expected_total_time
        )

        adapter = mock.Mock()
        adapter.store_instance_status.side_effect = raise_exc

        fake_check_output.return_value = response

        try:
            ping(address, adapter)
        except Exception as e:
            self.assertEqual(EXCEPTION_MESSAGE, e.message)

        adapter.store_instance_status.assert_called_with(
            address,
            expected_total_time,
            expected_exit_code,
            expected_packet_loss
        )

    @mock.patch('main.subprocess.check_output')
    def test_ping_exception_occured(self, fake_check_output):
        address = 'fake-address'
        expected_exit_code = '1'
        expected_packet_loss = '100'
        expected_total_time = '2000'

        adapter = mock.Mock()
        fake_check_output.side_effect = raise_exc
        adapter.store_instance_status.side_effect = raise_exc

        try:
            ping(address, adapter)
        except Exception as e:
            self.assertEqual(EXCEPTION_MESSAGE, e.message)

        adapter.store_instance_status.assert_called_with(
            address,
            expected_total_time,
            expected_exit_code,
            expected_packet_loss
        )
