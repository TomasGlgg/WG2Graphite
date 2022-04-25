from subprocess import run, PIPE
from json import loads
from time import time, monotonic, sleep
from pickle import dumps
from struct import pack
from socket import socket
from configparser import ConfigParser
from os import chdir, path


def get_data():
    proc = run('./wg-json.sh', stdout=PIPE)
    return loads(proc.stdout)


class MetricSender:
    sending_data = []
    last_data = None
    last_timestamp = None

    def _add_data(self, path, metric):
        self.sending_data.append((path, (int(time()), metric)))
        # print('Data added. Path: {}, metric: {}'.format(path, metric))

    def send_data(self):
        print('Sending data:', self.sending_data)
        if not self.sending_data: return
        payload = dumps(self.sending_data, protocol=2)
        self.sending_data.clear()
        header = pack("!L", len(payload))
        message = header + payload
        s = socket()
        try:
            s.connect((config.get('Graphite', 'host'), config.getint('Graphite', 'port')))
        except TimeoutError:
            print('Connection timeout')
            return
        s.send(message)
        s.close()

    @staticmethod
    def _process_data(data: dict):
        """
        :param data:
        {
        Interface: {
            "peers": {
                PublicKey: {
                        "transferRx": RX,
                        "transferTx": TX,
                        "allowedIps": [
                            IP
                        ]
                    }
                }
            }
        }
        :return:
        {
        IP: [
            RX,
            TX
            ]
        }
        """
        result = {}
        for peer in data[config.get('WG', 'interface')]['peers'].values():
            if not('transferRx' in peer and 'transferTx' and 'allowedIps' in peer and peer['allowedIps']):
                continue
            ip = peer['allowedIps'][0]
            rx = peer['transferRx']
            tx = peer['transferTx']
            result[ip] = (rx, tx)
        return result

    @staticmethod
    def path_by_ip(ip: str, end: str):
        ip = ip.removesuffix('/32').split('.')
        return '{}.{}.{}.{}'.format(config.get('Graphite', 'path'), ip[2], ip[3], end)

    def calculate_speed(self, new_data):
        if not new_data or not self.last_data: return
        if len(self.last_data) > len(new_data):  # WG rebooted
            print('Detected WG reboot')
            return
        for peer, traffic in new_data.items():
            if peer in self.last_data:
                rx_delta = new_data[peer][0] - self.last_data[peer][0]
                tx_delta = new_data[peer][1] - self.last_data[peer][1]
            else:
                rx_delta = new_data[peer][0]
                tx_delta = new_data[peer][1]
            if rx_delta < 0 or tx_delta < 0:  # WG rebooted
                self.sending_data.clear()
                print('Detected WG reboot')
                return
            rx_speed = rx_delta / (monotonic() - self.last_timestamp)
            tx_speed = tx_delta / (monotonic() - self.last_timestamp)
            self._add_data(self.path_by_ip(peer, 'rx'), rx_speed)
            self._add_data(self.path_by_ip(peer, 'tx'), tx_speed)

    def load(self, data):
        if not data:
            self.last_data.clear()
            print('WG data not found')
            return
        data = self._process_data(data)
        self.calculate_speed(data)
        self.last_data = data
        self.last_timestamp = monotonic()


def main():
    wg_data = get_data()
    metric.load(wg_data)
    metric.send_data()


if __name__ == '__main__':
    chdir(path.dirname(path.abspath(__file__)))
    config = ConfigParser()
    config.read('config.conf')
    metric = MetricSender()
    while True:
        main()
        sleep(config.getint('Main', 'interval'))
