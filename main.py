from subprocess import run, PIPE
from json import loads
from time import time, sleep
from pickle import dumps
from struct import pack
from socket import socket
from configparser import ConfigParser


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

    def delta(self, new_data):
        if not new_data or not self.last_data: return
        if len(self.last_data) > len(new_data):  # WG rebooted
            print('Detected WG reboot')
            return
        for peer, traffic in new_data.items():
            if peer in self.last_data:
                delta_rx = new_data[peer][0] - self.last_data[peer][0]
                delta_tx = new_data[peer][1] - self.last_data[peer][1]
            else:
                delta_rx = new_data[peer][0]
                delta_tx = new_data[peer][1]
            if delta_rx < 0 or delta_tx < 0:  # WG rebooted
                self.sending_data.clear()
                print('Detected WG reboot')
                return
            delta_rx /= time() - self.last_timestamp
            delta_tx /= time() - self.last_timestamp
            self._add_data(self.path_by_ip(peer, 'rx'), delta_rx)
            self._add_data(self.path_by_ip(peer, 'tx'), delta_tx)

    def load(self, data):
        if not data:
            self.last_data.clear()
            print('WG data not found')
            return
        data = self._process_data(data)
        self.delta(data)
        self.last_data = data
        self.last_timestamp = time()


def main():
    wg_data = get_data()
    metric.load(wg_data)
    metric.send_data()


if __name__ == '__main__':
    config = ConfigParser()
    config.read('config.conf')
    metric = MetricSender()
    while True:
        main()
        sleep(config.getint('Main', 'interval'))