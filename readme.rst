###############
Downtimer howto
###############

Overview
========

Downtimer is a daemon for monitoring state of an openstack upgrade while it’s running. The report can be formed both during upgrade process and at the end of an upgrade. In general, downtimer does the following:


* analyzes accessibility of OpenStack services and instances inside the cluster and writes this data into database; 
* creates report of downtimes of each OpenStack service and instance inside the cluster.

Running daemon
==============

Currently downtimer doesn’t have setup.py file, so for dealing with it we should work with main.py directly.


To start downtimer the one should use following command:

.. code:: text

 python main.py start

To stop it:


.. code:: text

 python main.py stop

To create report of cluster health:

.. code:: text

 python main.py report


Also report is created each time downtimer stopped.

Config file
===========

There are several settings that can be configured using config file which should be placed in /etc/downtimer/conf.ini. Here are example of conf.ini file:

.. code:: text

 [global]
 keystone_endpoint=http://172.29.236.10:5000
 user=admin
 password=secret
 report_file=/var/log/downtimer.report
 [db]
 host=monit-ent.vm.mirantis.net
 port=8086

Config file contains 2 sections - global and db. The db section contains all the settings related to database used for storing collected data while global section contains all the remaining settings.

global section
**************

**keystone_endpoint** contains keystone endpoint used to identify openstack cluster 

**user** and **password** settings specifies existing OpenStack user credentials that can be used for dealing with OpenStack services

**report_file** specifies path to the file which will contain report of cluster health

db section
**********

**host** and **port** points to influxdb host/port used to access database

Understanding report data
=========================

Here are example of report created by downtimer:

.. code:: text

 Service heat-cfn was down approximately 0 seconds which is 0.0% of total uptime
 Service nova was down approximately 16 seconds which is 0.0% of total uptime                                    
 Service cinder was down approximately 11 seconds which is 0.0% of total uptime
 Service neutron was down approximately 0 seconds which is 0.0% of total uptime
 Service keystone was down approximately 0 seconds which is 0.0% of total uptime
 Service heat was down approximately 0 seconds which is 0.0% of total uptime
 Service cinderv2 was down approximately 11 seconds which is 0.0% of total uptime
 Service glance was down approximately 57 seconds which is 0.0% of total uptime
 Address 172.16.166.151 was unreachable approximately 30855.0 second which is 90.5% of total uptime
 Address 172.16.166.154 was unreachable approximately 21.0 second which is 0.6% of total uptime
 Address 172.16.166.155 was unreachable approximately 23.0 second which is 0.7% of total uptime
 Address 172.16.166.156 was unreachable approximately 22.0 second which is 0.7% of total uptime
 Address 172.16.166.157 was unreachable approximately 20.0 second which is 0.6% of total uptime
 Address 172.16.166.158 was unreachable approximately 21.0 second which is 0.6% of total uptime

For each OpenStack service there is a separate line of report, describing it. In current version of downtimer only api services are taken into consideration.

Report of each services contains absolute data describing how much time this service was down and relative data in percents, describing percentage of time service was down.

For each floating IP associated with OpenStack instance inside the cluster there is also data in the same format.

When counting relative data only time period when downtimer was running is taken into consideration. So, for getting correct data of cluster health during an upgrade it’s important to run downtimer right after upgrade was started and stop at right after upgrade was finished.
