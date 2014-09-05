#! /usr/bin/python
# -*- coding: utf-8 -*-
import socket, sys, json, os, time, sqlite3, pprint, SocketServer, signal, base64, ctypes, struct
from datetime import datetime, timedelta
from multiprocessing import Process, Pipe
 
class pysync_sql(object):
    """Keeps track of all files"""
    def __init__( self, dbname=".pysyncfiles" ):
        self.dbname = dbname
        self.con = sqlite3.connect( self.dbname )
 
    def update_dir( self, file_dir=False ):
        if file_dir:
            with self.con:
                cur = self.con.cursor()
                cur.execute('SELECT name FROM sqlite_master WHERE type=\"table\" AND name=\"' + file_dir + '\"')
                if len(cur.fetchall()) < 1:
                    cur.execute('CREATE TABLE \"' + file_dir + '\"(id integer primary key AUTOINCREMENT, name TEXT, modified_by TEXT, modified_on TEXT, created datetime, modified datetime)')
        self.con.commit()
 
    def update_file( self, file_dir=False, file_properties=False ):
        if file_dir and file_properties:
            self.update_dir( file_dir )
            with self.con:
                cur = self.con.cursor()
                cur.execute('SELECT id FROM \"' + file_dir + '\" WHERE name=\"' + file_properties['name'] + '\"')
                if len(cur.fetchall()) < 1:
                    values = '\"' + str(file_properties['name']) + '\", ' + '\"' + str(file_properties['modified_by']) + '\", ' \
                        + '\"' + str(file_properties['modified_by']) + '\", ' + '\"' + str(file_properties['created']) + '\", ' \
                        + '\"' + str(file_properties['modified']) + '\"'
                    cur.execute('INSERT INTO \"' + file_dir + '\"(name, modified_by, modified_on, created, modified) VALUES(' + values + ')')
                else:
                    update = ( file_properties['modified_by'], file_properties['modified_on'], file_properties['modified'], file_properties['name'] )
                    cur.execute('UPDATE \"' + file_dir + '\" SET modified_by=?, modified_on=?, modified=? WHERE name=?', update )
        self.con.commit()

    def delete_file( self, file_dir, file_name ):
        with self.con:
            cur = self.con.cursor()
            cur.execute('DELETE FROM ? where name=?', ( file_dir, file_name ) )
        self.con.commit()

    def all_dirs( self ):
        with self.con:
            cur = self.con.cursor()
            cur.execute('SELECT name FROM sqlite_master WHERE type=\"table\" AND NOT name=\"sqlite_sequence\"')
            dirs = [ file_dir[0] for file_dir in cur.fetchall() ]
            self.con.commit()
            return dirs
 
    def all_files( self ):
        dirs = self.all_dirs()
        all_files = [];
        with self.con:
            for file_dir in dirs:
                cur = self.con.cursor()
                cur.execute('SELECT * FROM \"' + file_dir + '\"')
                files = cur.fetchall()
                for file_properties in files:
                    all_files.append( {
                        'id': file_properties[0],
                        'name': file_properties[1],
                        'modified_by': file_properties[2],
                        'modified_on': file_properties[3],
                        'created': file_properties[4],
                        'modified': file_properties[5],
                        'file_dir': file_dir
                        } )
            self.con.commit()
            return all_files
 
    def get_file( self, file_dir=False, file_name=False ):
        with self.con:
            cur = self.con.cursor()
            try:
                cur.execute('SELECT * FROM \"' + file_dir + '\" WHERE name=\"' + file_name + '\"')
                files = cur.fetchall()
                self.con.commit()
                return {
                    'id': files[0][0],
                    'name': files[0][1],
                    'modified_by': files[0][2],
                    'modified_on': files[0][3],
                    'created': files[0][4],
                    'modified': files[0][5],
                    'file_dir': file_dir
                    }
            except:
                self.con.commit()
                return False
 
class pysync_server(object):
    """Sends and recives files"""
    BAD_REQUEST = 400
 
    def __init__( self, pysync_dir=False, my_address="0.0.0.0", my_port=1234 ):
        self.my_address = my_address
        self.my_port = my_port
        self.pysync_server_address = my_address
        self.pysync_server_port = my_port
        if not pysync_dir:
            if os.name == 'nt':
                self.pysync_dir = os.path.abspath( os.path.expanduser("~") + "\\pysync\\" ) + "\\"
            else:
                self.pysync_dir = os.path.abspath( os.path.expanduser("~") + "/pysync/" ) + "/"
        else:
            self.pysync_dir = pysync_dir
        if not os.path.exists( self.pysync_dir ):
            os.makedirs( self.pysync_dir )
        self.sql = pysync_sql( dbname=self.pysync_dir+'.pysyncfiles' )
        if os.name == 'nt':
            ctypes.windll.kernel32.SetFileAttributesW(unicode(self.pysync_dir+'.pysyncfiles'), 0x02)
        else:
            import fcntl
        self.username = os.path.expanduser("~")
 
    def start( self ):
        self.make_host, am_i_host_conn = Pipe()
        self.change_host_pipe, watch_host = Pipe()
        self.am_i_host_process = Process( target=am_i_host, args=(am_i_host_conn,) )
        self.am_i_host_process.start()
        self.watch_process = Process( target=watch, args=(watch_host,) )
        self.watch_process.start()
 
    def is_host( self, is_host=False ):
        self.make_host.send(is_host)
 
    def change_host( self, change_host=False ):
        self.change_host_pipe.send(change_host)
 
    def send( self, data ):
        if self.pysync_server_address == '0.0.0.0' or self.pysync_server_address == self.get_lan_ip():
            return False
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server = (self.pysync_server_address, self.pysync_server_port)
        print 'Sending to ', server
        try:
            sock.connect( server )
        except:
            return "Couldn't connect to server on %s:%d" % server
        try:
            file_packet_length = '%015d' % len(data)
            sock.sendall( file_packet_length + data )
        except Exception as error:
            return "Couldn't send to server: ", error
        try:
            received = ''
            while (True):
                packet = sock.recv(1024).strip()
                while (packet):
                    received += packet
                    packet = sock.recv(1024).strip()
                break
        except:
            return "No response from server"
        finally:
            sock.close()
        if received:
            return received
 
    def handle_input( self, data ):
        data = self.unpack_packet( data, str(datetime.utcnow())[:7] )
        if data['type'] == "complete_file" and data['modified_on'] != socket.gethostname():
            self.sql.update_file( data )
            self.write_file( data )
        elif data['type'] == "get_db":
            return self.create_file_packet( self.pysync_dir+'.pysyncfiles', str(datetime.utcnow())[:7] )
        elif data['type'] == "get_file":
            return self.create_file_packet( self.pysync_dir+data['file_path'], str(datetime.utcnow())[:7] )
        elif data['type'] == "delete_file":
            try:
                os.remove( self.pysync_dir+data['file_path'] )
                self.sql.delete_file( data['file_dir'], data['file_name'] )
            except:
                pass
        return "OK"
 
    def encode( self, key, string ):
        encoded_chars = []
        for i in xrange(len(string)):
            key_c = key[i % len(key)]
            encoded_c = chr(ord(string[i]) + ord(key_c) % 256)
            encoded_chars.append(encoded_c)
        encoded_string = "".join(encoded_chars)
        return base64.urlsafe_b64encode(encoded_string)
 
    def write_file( self, file_packet ):
        if os.name == 'nt':
            file_packet['file_dir'] = file_packet['file_dir'].replace('/','\\')
        else:
            file_packet['file_dir'] = file_packet['file_dir'].replace('\\','/')
        write_to = self.real_path( file_packet['file_dir'], file_packet['name'] )
        if not os.path.exists( self.pysync_dir + file_packet['file_dir'] ):
            os.makedirs( self.pysync_dir + file_packet['file_dir'] )
        print "writing_to: ", write_to
        with open( write_to, 'wb' ) as replace_file:
            replace_file.write( file_packet['contents'] )
        if os.name == 'nt' and file_packet['name'][0] == '.':
            ctypes.windll.kernel32.SetFileAttributesW(unicode(write_to), 0x02)
        return True
 
    def decode( self, key, string ):
        string = base64.urlsafe_b64decode(string)
        decoded_chars = []
        for i in xrange(len(string)):
            key_c = key[i % len(key)]
            decoded_c = chr(ord(string[i]) - ord(key_c) % 256)
            decoded_chars.append(decoded_c)
        decoded_string = "".join(decoded_chars)
        return decoded_string
 
    def recv_msg( self, sock ):
        msg_length = int(sock.recv(15).strip())
        if not msg_length:
            return False
        return self.recvall( sock, msg_length )
 
    def recvall( self, sock, n ):
        data = ''
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet:
                return False
            data += packet
        return data
 
    def create_file_packet( self, file_path, key=False, contents=True, make_json=True ):
        file_dir, file_name = self.dir_and_name( file_path )
        if os.path.isfile( file_path ):
            file_packet = {
                'type': 'complete_file',
                'name': file_name,
                'file_dir': file_dir,
                'created': str(datetime.fromtimestamp( os.path.getctime(file_path) )),
                'modified': str(datetime.fromtimestamp( os.path.getmtime(file_path) )),
                'modified_by': self.username,
                'modified_on': socket.gethostname()
                }
            if contents:
                with open( file_path, 'rb' ) as file_contents:
                    file_packet['contents'] = base64.b64encode(''.join(file_contents))
            if make_json:
                file_packet = json.dumps( file_packet )
            if key:
                file_packet = self.encode( key, file_packet )
            return file_packet
        else:
            print "Couldn't find ", file_path
            return False
 
    def unpack_packet( self, packet, key=False ):
        if key:
            packet = self.decode( key, packet )
        packet = json.loads( packet )
        if packet['type'] == "complete_file":
            try:
                packet['contents'] = base64.b64decode(packet['contents'])
            except:
                pass
        return packet
 
    def send_file( self, file_path ):
        file_packet = self.create_file_packet( file_path, str(datetime.utcnow())[:7] )
        if file_packet:
            return self.send( file_packet )
        else:
            return "No such file"
 
    def scan_dir( self, directory ):
        contents = os.listdir(directory)
        for item in contents:
            if os.path.isdir( directory + item ):
                if os.name == 'nt':
                    self.scan_dir( directory + item + "\\" )
                else:
                    self.scan_dir( directory + item + "/" )
            if os.path.isfile( directory + item ):
                self.compare_file( directory + item )
 
    def compare_file( self, file_path ):
        file_packet = self.create_file_packet( file_path, contents=False, make_json=False )
        if (os.name == 'nt' and self.sql.dbname.split('\\')[-1] == file_packet['name']) or self.sql.dbname.split('/')[-1] == file_packet['name']:
            return False
        sql_record = self.sql.get_file( file_packet['file_dir'], file_packet['name'] )
        if not sql_record:
            self.sql.update_file( file_packet['file_dir'], file_packet )
            self.send_file( file_path )
            print "Created ", file_packet['name']
        else:
            sql_record['modified'] = datetime.strptime(sql_record['modified'].split('.')[0], "%Y-%m-%d %H:%M:%S")
            file_packet['modified'] = datetime.strptime(file_packet['modified'].split('.')[0], "%Y-%m-%d %H:%M:%S")
            # If it was modified elsewhere more recently
            if sql_record['modified'] < file_packet['modified']:
                self.sql.update_file( file_packet['file_dir'], file_packet )
                self.send_file( file_path )
                print "Updated ", file_packet['name']

    def update_sql( self, server_props ):
        if server_props:
            self.pysync_server_address = server_props['address']
            self.pysync_server_port = server_props['port']
        packet = {'type': 'get_db'}
        packet = self.encode( str(datetime.utcnow())[:7], json.dumps(packet) )
        response = self.send( packet )
        if response:
            sync_with = self.unpack_packet( response, str(datetime.utcnow())[:7] )
            sync_with['name'] = '.sync_with'
            self.write_file( sync_with )
            sync_with_path = self.real_path( '/','.sync_with')
            sync_with = pysync_sql( dbname=sync_with_path )
            server_files = sync_with.all_files()
            myfiles = self.sql.all_files()
            sync_with.con.close()
            os.remove( sync_with_path )
            for server_file in server_files:
                my_file = self.create_file_packet( self.real_path( server_file['file_dir'], server_file['name']), contents=False, make_json=False )
                if my_file:
                    my_file['modified'] = datetime.strptime(my_file['modified'].split('.')[0], "%Y-%m-%d %H:%M:%S")
                    server_file['modified'] = datetime.strptime(server_file['modified'].split('.')[0], "%Y-%m-%d %H:%M:%S")
                    # If it was modified elsewhere more recently
                    if my_file['modified'] < server_file['modified'] and server_file['modified_on'] != socket.gethostname():
                        print "\t", my_file['modified'], server_file['modified'], server_file['modified_on'], socket.gethostname()
                        packet = {'type': 'get_file', 'file_path': server_file['file_dir'] + server_file['name'] }
                        packet = self.encode( str(datetime.utcnow())[:7], json.dumps(packet) )
                        server_file = self.send( packet )
                        server_file = self.unpack_packet( self.send( packet ), str(datetime.utcnow())[:7] )
                        self.write_file( server_file )
                        server_file = self.create_file_packet( self.real_path( server_file['file_dir'], server_file['name']), contents=False, make_json=False )
                        self.sql.update_file( server_file )
                        print "Updated ", server_file['name']
                else:
                    print "\tlocal version not present"
                    packet = {'type': 'get_file', 'file_path': server_file['file_dir'] + server_file['name'] }
                    packet = self.encode( str(datetime.utcnow())[:7], json.dumps(packet) )
                    server_file = self.unpack_packet( self.send( packet ), str(datetime.utcnow())[:7] )
                    if server_file['modified_on'] != socket.gethostname():
                        self.write_file( server_file )
                        server_file = self.create_file_packet( self.real_path( server_file['file_dir'], server_file['name']), contents=False, make_json=False )
                        self.sql.update_file( server_file )
                        print "Created ", server_file['name']

    def real_path( self, file_dir, file_name ):
        if os.name == 'nt':
            file_dir = file_dir.replace('/','\\')
        else:
            file_dir = file_dir.replace('\\','/')
        if file_dir == u'/' or file_dir == u'\\':
            real_path = self.pysync_dir + file_name
        else:
            real_path = self.pysync_dir + file_dir + file_name
        return real_path

    def dir_and_name( self, file_path ):
        if os.name == 'nt':
            relitive_path = os.path.abspath( file_path ).split( self.pysync_dir )[1]
            file_dir = '\\'.join( relitive_path.split('\\')[:-1] ) + '\\'
            file_name = relitive_path.split('\\')[-1]
        else:
            relitive_path = os.path.abspath( file_path ).split( self.pysync_dir )[1]
            file_dir = '/'.join( relitive_path.split('/')[:-1] ) + '/'
            file_name = relitive_path.split('/')[-1]
        return file_dir, file_name

    def get_interface_ip( self, ifname ):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, struct.pack('256s',
                                ifname[:15]))[20:24])

    def get_lan_ip( self ):
        ip = socket.gethostbyname(socket.gethostname())
        if ip.startswith("127.") and os.name != "nt":
            interfaces = [
                "eth0",
                "eth1",
                "eth2",
                "wlan0",
                "wlan1",
                "wifi0",
                "ath0",
                "ath1",
                "ppp0",
                ]
            for ifname in interfaces:
                try:
                    ip = self.get_interface_ip(ifname)
                    break
                except IOError:
                    pass
        return ip
 
class pysync_connection_handler(SocketServer.BaseRequestHandler):
    def handle(self):
        server = pysync_server()
        message = server.recv_msg( self.request )
        #try:
        response = server.handle_input( message )
        #except:
        #    response = "ERROR"
        self.request.sendall( response )
 
def am_i_host( make_host ):
    server.server_process = Process( target=start_server )
    while True:
        is_host = make_host.recv()
        is_alive = False
        try:
            if server.server_process.is_alive():
                is_alive = True
        except:
            pass
        if is_host and not is_alive:
            server.server_process.start()
            print "I am now the host: ", server.get_lan_ip()
        elif not is_host and is_alive:
            print "I am no longer the host"
            try:
                server.server_process.terminate()
            except:
                server.server_process.TerminateProcess()
        time.sleep(10)
 
def start_server():
    socket_server = SocketServer.TCPServer((server.pysync_server_address, server.pysync_server_port), pysync_connection_handler)
    socket_server.serve_forever()
 
def watch( watch_host ):
    while True:
        if watch_host.poll():
            change = watch_host.recv()
        else: change = False
        if change:
            server.pysync_server_address = change['address']
            server.pysync_server_port = change['port']
        if os.path.isdir( server.pysync_dir ):
            server.scan_dir( server.pysync_dir )
        else:
            os.makedirs( server.pysync_dir )
        server.update_sql( change )
        time.sleep(5)
 
def signal_handler(signal, frame):
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
server = pysync_server()
 
if __name__ == '__main__':
    server.start()
    server.is_host(True)
    #server.change_host( { 'address': '10.7.198.148', 'port': 1234 } )
    #time.sleep(20)
    #server.is_host(False)
