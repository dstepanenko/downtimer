import json
import subprocess
import re
import requests
import time
import threading

import ConfigParser

from datetime import datetime
from urlparse import urlparse

def parse_config():
    CONF = ConfigParser.ConfigParser()
    CONF.read("conf.ini")
    #all this variables will become properties of the class
    #as soon as downtimer will be daemonized
    global host, port, db_host, db_port
    try:
        host = CONF.get('global', 'keystone_endpoint')
    except:
        host = "127.0.0.1"

    try:
        port = CONF.get('global', 'keystone_port')
    except:
        port = "5000"

    try:
        db_host = CONF.get('db', 'host')
    except:
        db_host = None

    try:
        db_port = CONF.get('db', 'port')
    except:
        db_port = None

def main():
    parse_config()
    global db_url
    db_url = 'http://{host}:{port}/write?db=endpoints'.format(
        host=db_host,
        port=db_port
    )

    data = {
        "auth": {
            "scope": {
                "project": {
                    "domain": {
                        "id": "default"
                    },
                    "name": "admin"
                }
            },
            "identity": {
                "password": {
                    "user": {
                        "domain": {
                            "id": "default"
                        },
                        "password": "secret",
                        "name": "admin"
                    }
                },
                "methods": [
                    "password"
                ]
            }
        }
    }
    data = json.dumps(data)
    url = 'http://{host}:{port}/v3/auth/tokens'.format(host=host, port=port)
    r = requests.post(url, data)
    result = r.json()

    services = result['token']['catalog']
    token = r.headers['X-Subject-Token']
    endpoints = parse_endpoints(services)
    floating_ips = get_floating_ips(services, token)
    for ip in floating_ips:
        worker = threading.Thread(target=ping,
                                  args=(ip,))
        worker.daemon = True
        worker.start()

    print(endpoints)
    print token
    for endpoint, address in endpoints:
        worker = threading.Thread(target=do_check,
                                  args=(endpoint, address, token))
        worker.daemon = True
        worker.start()


SERVICE_TIMEOUT = 0.9


def do_check(endpoint, address, token):
    while True:
        try:
            timeout = 0
            headers = {'X-Auth-Token': token}
            r = requests.get(address, headers=headers, timeout=SERVICE_TIMEOUT)
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

def get_floating_ips(services, token):
    url = None
    for service in services:
        if service['type'] == 'compute':
            url = service['endpoints'][0]['url']+ '/os-floating-ips'
    if url is None:
        raise Exception("No compute found!")
    headers = {'X-Auth-Token': token}
    resp = requests.get(url, headers=headers)
    ips = resp.json()
    result = [ip['ip'] for ip in ips['floating_ips']
              if ip['instance_id'] != None]
    return result
    
    
def ping(address):
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

def parse_endpoints(services):
    endpoints = []
    for service in services:
        url = urlparse(service['endpoints'][0]['url'])
        host = "http://" + url.hostname + ":" + str(url.port) + "/"
        endpoints.append((service['name'], host))
    return endpoints


if __name__ == "__main__":
    main()
    while True:
        time.sleep(3)
