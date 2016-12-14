# downtimer
Utility for gather downtime metrics of openstack

## How to install:

```
sudo apt-get install python-pip virtualenv

git clone https://github.com/dstepanenko/downtimer.git && cd downtimer

virtualenv .venv && source .venv/bin/activate

pip install -r requirements.txt

python setup.py install

sudo mkdir /var/log/downtimer
sudo chown $USER /var/log/downtimer
sudo chmod 664 /var/log/downtimer

mkdir /etc/downtimer
cp conf.ini.sample /etc/downtimer/conf.ini

downtimer
```
