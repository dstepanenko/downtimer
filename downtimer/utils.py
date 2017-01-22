from datetime import datetime
import re
import requests
import subprocess
import time

SERVICE_TIMEOUT = 0.9


def do_check(endpoint, address, db_adapter):
    while True:
        start_time = time.time()
        try:
            timeout = 0
            r = requests.head(address, timeout=SERVICE_TIMEOUT)
            status_msg = 'FAIL'
            if r.status_code >= 400:
                # In the event that the endpoint URL returns a status code
                #  >=400, test again using the "healcheck" URL, IE:
                #  "http://<service_endpoint>/<service_port>/healthcheck"
                #  before marking the endpoint as down.
                _address = address + 'healthcheck'
                r = requests.get(_address, timeout=SERVICE_TIMEOUT)
                if r.status_code < 300:
                    address = _address
                    status_msg = 'OK'
            else:
                status_msg = 'OK'

            print(endpoint + " " + address + ": " + str(r.status_code) + " "
                  + status_msg + " " + str(datetime.now()) + "\n")

            elapsed = r.elapsed.microseconds
            status_code = r.status_code
        except requests.exceptions.RequestException as e:
            timeout = 1
            elapsed = SERVICE_TIMEOUT * 1e6
            status_code = 408
            print e
        except Exception as e:
            print("This situation should\'t have occured. Failed to check "
                  "address {} with exception {}".format(address, e.message))
            raise e

        db_adapter.store_service_status(endpoint, address, status_code,
                                        timeout, elapsed)

        finish_time = time.time()
        '''
        Counting time spent on all this code execution in seconds
        to make all the time gaps between consecutive measurements equal
        '''
        time_spent = finish_time - start_time
        if time_spent < 2:
            time.sleep(2 - time_spent)


def ping(address, db_adapter):
    while True:
        start_time = time.time()
        try:
            response = subprocess.check_output(
                ['ping', '-i', '0.2', '-c', '5', '-W', '1', address],
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
            total_time = '1000'

        db_adapter.store_instance_status(address, total_time,
                                         exit_code, packet_loss)
        finish_time = time.time()
        '''
        Counting time spent on all this code execution in seconds
        to make all the time gaps between consecutive measurements equal
        '''
        time_spent = finish_time - start_time
        if time_spent < 2:
            time.sleep(2 - time_spent)
