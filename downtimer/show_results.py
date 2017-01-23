#!/usr/bin/env python

import main

_downtimer = main.Downtimer()
adapter = _downtimer.db_adapter


for service in adapter.get_service_statuses():
    _srv_downtime = service.get('srv_downtime', 0)
    _total_uptime = service.get('total_uptime', 1)
    _service_down_time = ((100.0 * _srv_downtime) / _total_uptime)
    print(
        "Service %s was down approximately %d seconds which are %.1f"
        "%% of total uptime" % (
            service['service'], service['srv_downtime'], _service_down_time
        )
    )


for address in adapter.get_instance_statuses():
    _failed = address.get('failed', 0)
    _total_time = address.get('total_time', 1)
    _address_down_time = ((100.0 * _failed) / _total_time)
    print(
        "Address %s was unreachable approximately %.1f second which are"
        " %.1f %% of total uptime" % (
            address['address'], _failed, _address_down_time
        )
    )
