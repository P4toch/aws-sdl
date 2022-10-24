import traceback

import sys

from rtech.connector.connector import Connector

from smb.SMBConnection import SMBConnection


class SambaConnector(Connector):
    # __init__
    def __init__(self, config, connector_name, connector_config):
        super(SambaConnector, self).__init__(config)

        self.logger.info('Initializing SambaConnector ...')

        self.connector_config = connector_config

        self.name = connector_name
        if self.name == 'custom':
            self.type = connector_config['type']
            self.server = connector_config['server']
            self.domain = connector_config['domain']
            self.use_ntlm_v2 = connector_config['use_ntlm_v2']
            self.is_direct_tcp = connector_config['is_direct_tcp']
            self.server_ip = connector_config['server_ip']
            self.port = connector_config['port']
            self.client_machine = connector_config['client_machine']
            self.login = connector_config['login']
            self.password = connector_config['password']
        else:
            self.type = self.config.file_shares[self.name]['type']
            self.server = self.config.file_shares[self.name]['server']
            self.domain = self.config.file_shares[self.name]['domain']
            self.use_ntlm_v2 = self.config.file_shares[self.name]['use_ntlm_v2']
            self.is_direct_tcp = self.config.file_shares[self.name]['is_direct_tcp']
            self.server_ip = self.config.file_shares[self.name]['server_ip']
            self.port = self.config.file_shares[self.name]['port']
            self.client_machine = self.config.file_shares[self.name]['client_machine']
            self.login = self.config.file_shares[self.name]['login']
            self.password = self.config.file_shares[self.name]['password']

        self.conn = None

    # __enter__
    def __enter__(self):
        if not self.conn:
            self.logger.info('Opening Samba Session: ' + self.name)
            try:
                self.conn = SMBConnection(
                    username=self.login,
                    password=self.password,
                    my_name=self.client_machine,
                    remote_name=self.server,
                    domain=self.domain,
                    use_ntlm_v2=self.use_ntlm_v2,
                    is_direct_tcp=self.is_direct_tcp
                )

                connected = self.conn.connect(ip=self.server_ip, port=self.port, timeout=180)
                if not connected:
                    raise Exception
            except Exception as e:
                if self.name == 'custom':
                    self.logger.error('Cannot connect to samba share: ' + self.server)
                else:
                    self.logger.error('Cannot connect to samba share: ' + self.name)
                self.logger.error(e)
                self.logger.error(traceback.format_exc())

                sys.exit(1)
        return self

    # __exit__
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.logger.info('Closing Samba Session: ' + self.name)
            self.conn.close()
