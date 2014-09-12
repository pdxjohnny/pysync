#! /usr/bin/python
# -*- coding: utf-8 -*-
import socket, sys, json, os, time, sqlite3, pprint, SocketServer, signal, base64, ctypes, struct, urllib, traceback, ssl, Cookie, argparse, getpass, random, codecs
from datetime import datetime, timedelta
from multiprocessing import Process, Pipe, Lock, freeze_support
if os.name != 'nt':
    import fcntl

class pysync_sql(object):
    """Keeps track of all files"""
    def __init__( self, dbname=".pysyncfiles" ):
        self.dbname = dbname
        self.con = sqlite3.connect( self.dbname )
        with self.con:
            cur = self.con.cursor()
            cur.execute('SELECT name FROM sqlite_master WHERE type=\"table\" AND name=\"pysync_users\"')
            if len(cur.fetchall()) < 1:
                cur.execute('CREATE TABLE \"pysync_users\"(username TEXT, password TEXT, pysync_key TEXT)')
                self.con.commit()
 
    def update_dir( self, file_dir=False ):
        if file_dir:
            with self.con:
                cur = self.con.cursor()
                cur.execute('SELECT name FROM sqlite_master WHERE type=\"table\" AND name=\"' + file_dir + '\"')
                if len(cur.fetchall()) < 1:
                    cur.execute('CREATE TABLE \"' + file_dir + '\"(id integer primary key AUTOINCREMENT, name TEXT, modified_by TEXT, modified_on TEXT, created datetime, modified datetime, status TEXT)')
                    self.con.commit()
 
    def update_file( self, file_dir=False, file_properties=False ):
        if file_dir and file_properties:
            file_dir = file_dir.replace('\\','/')
            self.update_dir( file_dir )
            with self.con:
                cur = self.con.cursor()
                cur.execute('SELECT id FROM \"' + file_dir + '\" WHERE name=\"' + file_properties['name'] + '\"')
                if len(cur.fetchall()) < 1:
                    values = '\"' + str(file_properties['name']) + '\", ' + '\"' + str(file_properties['modified_by']) + '\", ' \
                        + '\"' + str(file_properties['modified_on']) + '\", ' + '\"' + str(file_properties['created']) + '\", ' \
                        + '\"' + str(file_properties['modified']) + '\"'
                    cur.execute('INSERT INTO \"' + file_dir + '\"(name, modified_by, modified_on, created, modified) VALUES(' + values + ')')
                else:
                    update = ( file_properties['modified_by'], file_properties['modified_on'], file_properties['modified'], file_properties['name'] )
                    cur.execute('UPDATE \"' + file_dir + '\" SET modified_by=?, modified_on=?, modified=? WHERE name=?', update )
                self.con.commit()

    def delete_file( self, file_dir, file_name ):
        file_dir = file_dir.replace('\\','/')
        with self.con:
            cur = self.con.cursor()
            cur.execute('DELETE FROM \"' + file_dir + '\" where name=\"' + file_name + '\"')
            self.con.commit()

    def exists( self, table, column, should_be ):
        with self.con:
            cur = self.con.cursor()
            cur.execute('SELECT \"' + column + '\" FROM \"' + table + '\" WHERE \"' + column + '\"=\"' + should_be + '\"')
            if len(cur.fetchall()) < 1:
                return True
            else:
                return False
        self.con.commit()
        self.con.close()

    def all_dirs( self ):
        with self.con:
            cur = self.con.cursor()
            cur.execute('SELECT name FROM sqlite_master WHERE type=\"table\" AND NOT name=\"sqlite_sequence\" AND NOT name=\"pysync_users\"')
            dirs = [ file_dir[0] for file_dir in cur.fetchall() ]
            self.con.commit()
            return dirs
 
    def all_files( self, table=False ):
        dirs = self.all_dirs()
        all_files = [];
        with self.con:
            if table:
                table = table.replace('\\','/')
                cur = self.con.cursor()
                cur.execute('SELECT * FROM \"' + table + '\"')
                files = cur.fetchall()
                for file_properties in files:
                    all_files.append( {
                        'id': file_properties[0],
                        'name': file_properties[1],
                        'modified_by': file_properties[2],
                        'modified_on': file_properties[3],
                        'created': file_properties[4],
                        'modified': file_properties[5],
                        'file_dir': table
                        } )
            else:
                for file_dir in dirs:
                    cur = self.con.cursor()
                    cur.execute('SELECT * FROM \"' + file_dir + '\"')
                    for file_properties in cur.fetchall():
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

    def all_files_by_dir( self ):
        dirs = self.all_dirs()
        all_files_by_dir = {}
        with self.con:
            for file_dir in dirs:
                all_files_by_dir[file_dir] = []
                cur = self.con.cursor()
                cur.execute('SELECT \"id\", \"name\" FROM \"' + file_dir + '\"')
                files = cur.fetchall()
                for file_properties in files:
                    all_files_by_dir[file_dir].append( {
                        'id': file_properties[0],
                        'name': file_properties[1]
                        } )
            self.con.commit()
            return all_files_by_dir
 
    def get_file( self, file_dir=False, file_name=False ):
        file_dir = file_dir.replace('\\','/')
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
 
    def __init__( self, pysync_dir=False, my_address="0.0.0.0", my_port=3639 ):
        self.my_address = my_address
        self.my_port = my_port
        self.pysync_server_address = my_address
        self.pysync_server_port = my_port
        key_dir = os.path.dirname(__file__)
        self.ssl_cert = os.path.join(key_dir, 'server.crt')
        if not pysync_dir:
            if os.name == 'nt':
                self.pysync_dir = os.path.abspath( os.path.expanduser("~") + "\\pysync\\" ) + "\\"
            else:
                self.pysync_dir = os.path.abspath( os.path.expanduser("~") + "/pysync/" ) + "/"
        else:
            self.pysync_dir = pysync_dir
        if not os.path.exists( self.pysync_dir ):
            os.makedirs( self.pysync_dir )
        if os.name == 'nt':
            ctypes.windll.kernel32.SetFileAttributesW(unicode(self.pysync_dir+'.pysyncfiles'), 0x02)
        else:
            import fcntl
        self.username = os.path.expanduser("~")
 
    def start( self ):
        self.make_host, am_i_host_conn = Pipe()
        self.change_host_pipe, watch_host = Pipe()
        self.watch_lock = Lock()
        self.am_i_host_process = Process( target=am_i_host, args=(am_i_host_conn,) )
        self.am_i_host_process.start()
        self.watch_process = Process( target=watch, args=(watch_host, self.watch_lock) )
        self.watch_process.start()
 
    def is_host( self, is_host=False ):
        self.make_host.send(is_host)
 
    def change_host( self, change_host=False ):
        print "Testing connection to host..."
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock = ssl.wrap_socket(sock,
                           ca_certs=self.ssl_cert,
                           cert_reqs=ssl.CERT_REQUIRED)
        test_con = (change_host['address'], change_host['port'])
        sock.connect( test_con )
        if self.change_host_pipe.poll():
            self.change_host_pipe.recv()
        self.change_host_pipe.send(change_host)
        print "[   OK  ] Host changed"

    def send( self, data ):
        if self.pysync_server_address == '0.0.0.0' or self.pysync_server_address == self.get_lan_ip():
            return False
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock = ssl.wrap_socket(sock,
                           ca_certs=self.ssl_cert,
                           cert_reqs=ssl.CERT_REQUIRED)
        server = (self.pysync_server_address, self.pysync_server_port)
        #print "Sending to ", server
        try:
            sock.connect( server )
        except:
            raise pysync_connection_error("[ ERROR ] Couldn't connect to server on %s:%s" % server, set_host_parms )
        try:
            file_packet_length = '%015d' % len(data)
            sock.sendall( file_packet_length + data )
        except Exception as error:
            return "[ ERROR ] Couldn't send to server: ", error
        try:
            received = ''
            while (True):
                packet = sock.recv(1024).strip()
                while (packet):
                    received += packet
                    packet = sock.recv(1024).strip()
                break
        except:
            return "[ ERROR ] No response from server"
        finally:
            sock.close()
        if received:
            return received

    def handle_input( self, data ):
        if type(data) is bool:
            return str(self.BAD_REQUEST)
        try:
            if 'GET' in data or 'POST' in data:
                return self.https_server( data )
        except Exception, e:
            print e
            traceback.print_exc()
        try:
            data = self.unpack_packet( data, str(datetime.utcnow())[:7] )
        except:
            try:
                data = self.unpack_packet( data )
            except Exception, e:
                return "[ ERROR ] Couldn't unpack either way", e
        if data['type'] == "complete_file" and data['modified_on'] != socket.gethostname():
            # Write the file
            self.write_file( data )
            print "Wrote %s %s " % ( data['file_dir'], data['name'] )
            # Set the date to after it was finished being writin
            data['modified'] = str(datetime.now())
            # Update the sql
            sql = pysync_sql( dbname=self.real_path('/','.pysyncfiles') )
            sql.update_file( data['file_dir'], data )
            sql.con.close()
            print "Updated sql %s %s " % ( data['file_dir'], data['name'] )
            del data['contents']
            data = json.dumps( data )
            #data = self.encode( str(datetime.utcnow())[:7], data )
            return data
        elif data['type'] == "get_db":
            return self.create_file_packet( self.real_path('/','.pysyncfiles'), str(datetime.utcnow())[:7] )
        elif data['type'] == "get_file":
            return self.create_file_packet( self.real_path( data['file_dir'], data['name'] ), str(datetime.utcnow())[:7] )
        elif data['type'] == "update_sql":
            sql = pysync_sql( dbname=self.real_path('/','.pysyncfiles') )
            print "Before sql update", sql.get_file( data['file_dir'], data['name'] )['modified_on']
            sql.update_file( data['file_dir'], data )
            print "After sql update", sql.get_file( data['file_dir'], data['name'] )['modified_on']
            sql.con.close()
        #elif data['type'] == "delete_file":
        #    try:
        #        os.remove( self.pysync_dir+data['file_path'] )
        #        sql = pysync_sql( dbname=self.real_path('/','.pysyncfiles') )
        #        sql.delete_file( data['file_dir'], data['file_name'] )
        #        sql.con.close()
        #    except:
        #        pass
        return "OK"

    def https_server( self, data, page=False, add_headers=False ):
        if not page:
            if type(data) is bool:
                return self.BAD_REQUEST
            elif 'GET' in data:
                page = data[data.index('GET')+4 : data.index('HTTP')]
                try:
                    if page[-1] == ' ':
                        page = page[:-1]
                except Exception, e:
                    print "[ ERROR ] ", e
                    print "[ ERROR ] Page was: ", page
            elif 'POST' in data:
                page = data[data.index('POST')+5 : data.index('HTTP')]
                try:
                    if page[-1] == ' ':
                        page = page[:-1]
                except Exception, e:
                    print "[ ERROR ] ", e
                    print "[ ERROR ] Page was: ", page
                return self.https_post_response( page, data )
            else:
                return self.BAD_REQUEST
        page = urllib.unquote( page ).decode('utf8')
        cookies = self.get_cookies( data )

        output = [
'''
<!DOCTYPE html>
<html>
<head>
    <title>Py Sync</title>

    <meta name="viewport" content="width=device-width, initial-scale=1">

    <link rel="shortcut icon" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAABy0lEQVRYR2NkGGDAOMD2M4w6YDQERkNgcIaAcegqfmLKh7Orwz5iU4dPP7oerCFgF7H0PzEOAKp5dmhFtDSyWmL0AvXA7cXqAMfYlcQ6gOEPC6PY4flhr0GOIEXf/sXhYLsxHOCSuK6QkZGhj8gQACvbPS+I0TVpHbqjPwGlQBgE+KAYbixID1YHeKRvwvD9jpl+cIdik//PyBDH+J9hEbKjCemByWOEgHfONgwHbJ3iBVbnkLWKh5uJ5zOyRf///89hZGScQmyIwcyCqcdwgF/hLhQHADmnNve7mYM0+Bbu+g3UwIJs2aZ+N0Z0PXgdw8hUtanPpR2rAwJL9xUCUwVJ8b++ywnsicCyfUQnXJgejDQQUn2IaENAmte02qGEILH6kfWhGBDecJxoB6xssATrxaYHJkeMPIoDolpPo8f/XWAim4Qcp4yMTP+XV5tMhomh6wGJL6s2hZtLSB6uMLbrQiEDw3+U+F9cZkiwrojtOv8HaCczsbkA3Uy4BQn9lzGCf0GhLkEHgCzGpheLgz4AzRNEF4dbkDzlOoYD5uZoEuWApEnXixmZGHpwhcJfRkbPBdkaO7DJE2UBscFLjrpRB4yGwGgIjIYAAFvsmiFDG+h+AAAAAElFTkSuQmCC" />
    <link rel="stylesheet" href="https://code.jquery.com/mobile/1.4.3/jquery.mobile-1.4.3.min.css" />
    <script src="https://code.jquery.com/jquery-1.11.1.min.js"></script>
    <script src="https://code.jquery.com/mobile/1.4.3/jquery.mobile-1.4.3.min.js"></script>
</head>
<body>
''',
'''
<div data-role="page">

    <div data-role="header">
        <a href="#" data-rel="back" class="ui-btn-left ui-btn ui-icon-back ui-btn-icon-notext ui-shadow ui-corner-all" data-role="button" role="button">Back</a>
        <h1>Py Sync</h1>
    </div><!-- /header -->

    <div role="main" class="ui-content">
        <ul data-role="listview" data-filter="true" data-filter-placeholder="Search files..." data-inset="true">''', '''
        </ul>
    </div><!-- /content -->''','''

    <div data-role="footer">
        <h4>''', socket.gethostname(), '''</h4>
    </div><!-- /footer -->
</div><!-- /page -->''',
'''
<style>
html{ font-family: "Myriad Set Pro","Lucida Grande","Helvetica Neue","Helvetica","Arial","Verdana","sans-serif";}
</style>
</body>
</html>
''' ]
        if not self.validate_pysync_key( cookies ):
            output[1] = '''
<div data-role="page" data-dialog="true">

    <div data-role="header">
        <h1>Login</h1>
    </div><!-- /header -->

    <div role="main" class="ui-content">
        <h1>Login</h1>
        <form action="/login" method='post' data-ajax="false" >
            <div data-role="fieldcontain">
                <label for="username">Username:</label>
                <input type="text" name="username" id="username" />
            </div>
            <div data-role="fieldcontain">
                <label for="password">Password:</label>
                <input type="password" name="password" id="password" />
            </div>
            <div data-role="fieldcontain">
                <center>
                    <input type="submit" value="Login" />
                </center>
            </div>
'''
            output[2] = '''
        </form>
    </div><!-- /content -->
'''
        elif page == '/' or page == '/login' :
            sql = pysync_sql( dbname=self.real_path('/','.pysyncfiles') )
            all_dirs = sql.all_files_by_dir()
            sql.con.close()
            for row in all_dirs['/']:
                output.insert(2, '\n<li><a href="/'+row['name']+'" data-transition="flip" >'+row['name']+'</a></li>')
            for directory in all_dirs:
                if directory != '/' and directory.count('/') is 1:
                    output.insert(2, '\n<li><a href="/'+directory+'" data-transition="flip" >'+directory+'</a></li>')
        elif page.startswith( '/download::' ):
            headers, output = self.download( page.split( '/download::' )[1], cookies )
            return headers + output
        elif page[-1] == '/':
            table = page[1:]
            sql = pysync_sql( dbname=self.real_path('/','.pysyncfiles') )
            all_dirs = sql.all_files_by_dir()
            sql.con.close()
            for row in all_dirs[table]:
                output.insert(2, '\n<li><a href="/'+table+row['name']+'" data-transition="flip" >'+row['name']+'</a></li>')
            for directory in all_dirs:
                if directory.startswith(table) and directory.count('/') is table.count('/')+1:
                    output.insert(2, '\n<li><a href="/'+directory+'" data-transition="flip" >'+directory+'</a></li>')
        else:
            file_dir = '/'.join(page.split('/')[:-1])
            file_dir += '/'
            file_name = page.split('/')[-1]
            if len(file_dir) > 1:
                file_dir = file_dir[1:]
            output[1] = '''
<div data-role="page" data-dialog="true">

    <title>''' +file_name+ '''</title>

    <div data-role="header">
        <h1>''' +file_name+ '''</h1>
    </div><!-- /header -->

    <div role="main" class="ui-content">
        <ul data-role="listview" data-inset="true">'''
            sql = pysync_sql( dbname=self.real_path('/','.pysyncfiles') )
            request_file = sql.get_file( file_dir, file_name )
            sql.con.close()
            if request_file:
                output.insert(2, '''
<script>
function pysync_file_download(){
    $.post('/download', {'download':\'''' + page + '''\'}, function(retData){
        var binUrl = retData.url;
        document.body.innerHTML += "<iframe src='" + binUrl + "' style='display: none;' ></iframe>"
    });
}
</script>
<li><a href="/download::''' + page + '''" data-ajax="false" >Download</a></li>
<li><a href="/edit::''' + page + '''" target="_blank" >Edit</a></li>
<li><a href="#popupDialog" data-rel="popup" data-position-to="window" data-transition="pop" >Delete</a></li>
<div data-role="popup" id="popupDialog" data-dismissible="false" style="max-width:400px;">
    <div data-role="header" data-theme="a">
    <h1>Delete File?</h1>
    </div>
    <div role="main" class="ui-content">
        <h3 class="ui-title">Are you sure you want to delete this file?</h3>
    <p>This action cannot be undone.</p>
        <a href="#" class="ui-btn ui-corner-all ui-shadow ui-btn-inline ui-btn-b" data-rel="back">Cancel</a>
        <a href="/delete::''' + page + '''" class="ui-btn ui-corner-all ui-shadow ui-btn-inline ui-btn-b" data-rel="back" data-transition="flow" >Delete</a>
    </div>
</div>
''' )
                output.insert(2, '\n<li data-role="list-divider" >File Options</li>')
                for prop in request_file:
                    output.insert(2, '\n<li><a href="#" data-transition="flip" >'+str(request_file[prop])+'</a></li>')
                    output.insert(2, '\n<li data-role="list-divider" >'+str(prop)+'</li>')
        headers = "HTTP/1.1 200 OK\n"
        headers += "Content length: %d\n" % len(''.join(output))
        headers += "Content-Type: text/html\n"
        if not add_headers:
            return ''.join(output)
        else:
            return headers + ''.join(output)

    def https_post_response( self, page, data ):
        cookies = self.get_cookies( data )
        form_data = self.get_form_data( data )
        output = []
        headers = False
        sql = pysync_sql( dbname=self.real_path('/','.pysyncfiles') )
        if 'username' in form_data and 'password' in form_data:
            with sql.con:
                cur = sql.con.cursor()
                cur.execute('SELECT username FROM pysync_users WHERE username=\"' + form_data['username'] + '\" AND password=\"' + form_data['password'] + '\"')
                if len(cur.fetchall()) is 1:
                    pysync_key = self.encode( str(random.random()), form_data['username']*3 )
                    output.append( self.https_server( data, page, add_headers=False ) )
                    output.insert( 0, '<meta http-equiv="refresh" content="0; url=/" />' )
                    headers = "HTTP/1.1 200 OK\n"
                    headers += "Content length: %d\n" % len(''.join(output))
                    headers += "Content-Type: text/html\n"
                    headers += "Set-Cookie: pysync_key="+pysync_key+"; expires="+str(datetime.utcnow()+timedelta(days=1)).split('.')[0]+"; secure\n"
                    headers += "Set-Cookie: pysync_username=\""+form_data['username']+"\"; expires="+str(datetime.utcnow()+timedelta(days=1)).split('.')[0]+"; secure\n\n"
                    cur.execute('UPDATE pysync_users SET pysync_key=\"' + pysync_key + '\" WHERE username=\"' + form_data['username'] + '\" AND password=\"' + form_data['password'] + '\"')
                    print '[  LOG  ]  User \"' + form_data['username'] + '\" logded in'
                else:
                    output.append( json.dumps({'login': 'FAIL'}) )
        elif 'download' in form_data:
            headers, output = self.download( form_data['download'], cookies )
        else:
            output.append( json.dumps(cookies) )
            output.append( json.dumps(form_data) )
            output.append( data )
            output.insert(0, "\n\n" )
        if not headers:
            headers = "HTTP/1.1 200 OK\n"
            headers += "Content length: %d\n" % len(''.join(output))
            headers += "Content-Type: text/html\n"
        return headers + ''.join(output)

    def download( self, file_path, cookies ):
        if self.validate_pysync_key( cookies ):
            file_dir = '/'.join(file_path.split('/')[:-1])
            file_dir += '/'
            file_name = file_path.split('/')[-1]
            if len(file_dir) > 1:
                file_dir = file_dir[1:]
            file_path = self.real_path( file_dir, file_name )
            output = ''
            if os.path.exists(file_path):
                with open( file_path, 'rb' ) as download:
                    output = download.read()
            headers = "HTTP/1.1 200 OK\n"
            headers += "Content length: %d\n" % len(output)
            headers += "Content-Type: application/octet-stream\n"
            headers += 'Content-Disposition: attachment;filename=\"' + file_name + '\"\n\n'
            try:
                return headers.encode("utf-8"), output.encode("utf-8")
            except Exception, e:
                output = '''
<!DOCTYPE html>
<html>
<head>
    <title>Py Sync</title>

    <meta name="viewport" content="width=device-width, initial-scale=1">

    <link rel="shortcut icon" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAABy0lEQVRYR2NkGGDAOMD2M4w6YDQERkNgcIaAcegqfmLKh7Orwz5iU4dPP7oerCFgF7H0PzEOAKp5dmhFtDSyWmL0AvXA7cXqAMfYlcQ6gOEPC6PY4flhr0GOIEXf/sXhYLsxHOCSuK6QkZGhj8gQACvbPS+I0TVpHbqjPwGlQBgE+KAYbixID1YHeKRvwvD9jpl+cIdik//PyBDH+J9hEbKjCemByWOEgHfONgwHbJ3iBVbnkLWKh5uJ5zOyRf///89hZGScQmyIwcyCqcdwgF/hLhQHADmnNve7mYM0+Bbu+g3UwIJs2aZ+N0Z0PXgdw8hUtanPpR2rAwJL9xUCUwVJ8b++ywnsicCyfUQnXJgejDQQUn2IaENAmte02qGEILH6kfWhGBDecJxoB6xssATrxaYHJkeMPIoDolpPo8f/XWAim4Qcp4yMTP+XV5tMhomh6wGJL6s2hZtLSB6uMLbrQiEDw3+U+F9cZkiwrojtOv8HaCczsbkA3Uy4BQn9lzGCf0GhLkEHgCzGpheLgz4AzRNEF4dbkDzlOoYD5uZoEuWApEnXixmZGHpwhcJfRkbPBdkaO7DJE2UBscFLjrpRB4yGwGgIjIYAAFvsmiFDG+h+AAAAAElFTkSuQmCC" />
    <link rel="stylesheet" href="https://code.jquery.com/mobile/1.4.3/jquery.mobile-1.4.3.min.css" />
    <script src="https://code.jquery.com/jquery-1.11.1.min.js"></script>
    <script src="https://code.jquery.com/mobile/1.4.3/jquery.mobile-1.4.3.min.js"></script>
</head>
<body>
<div data-role="page" data-dialog="true">
    <title>Download Failed</title>

    <div data-role="header">
        <h1>Download Failed</h1>
    </div><!-- /header -->

    <div role="main" class="ui-content">
        <h1>Download Failed</h1>
        <p>
        [ ERROR ] ''' + str(e) + '''<br><br>
        ''' +  traceback.format_exc() + '''
        </p>
    </div><!-- /content -->
</div><!-- /page -->
</body>
</html>'''
                headers = "HTTP/1.1 200 OK\n"
                headers += "Content length: %d\n" % len(output)
                headers += "Content-Type: text/html\n\n"
                return headers.encode("utf-8"), output.encode("utf-8")
        else:
            output = '''\n\n
<div data-role="page" data-dialog="true">
    <title>Verification Failed</title>

    <div data-role="header">
        <h1>Verification Failed</h1>
    </div><!-- /header -->

    <div role="main" class="ui-content">
        <h1>Verification Failed</h1>
        <p>Please sign in to verify identity</p>
    </div><!-- /content -->
</div><!-- /page -->'''
        return headers.encode("utf-8"), output.encode("utf-8")

    def validate_pysync_key( self, cookies ):
        res = False
        if 'pysync_key' in cookies and 'pysync_username' in cookies:
            sql = pysync_sql( dbname=self.real_path('/','.pysyncfiles') )
            with sql.con:
                cur = sql.con.cursor()
                cur.execute('SELECT pysync_key FROM pysync_users WHERE username=\"' + cookies['pysync_username'] + '\"')
                try:
                    if cookies['pysync_key'] == cur.fetchall()[0][0]:
                        res = True
                except Exception, e:
                    print e, cookies['pysync_username'], cookies['pysync_key']
        return res

    def get_cookies( self, data ):
        cookies = []
        lines = data.split('\r\n')
        for line in xrange(0,len(lines)):
            if "Cookie:" in lines[line]:
                c = Cookie.SimpleCookie()
                c.load(lines[line])
                cookies.append(c)
        parts = {}
        for cookie in cookies:
            for attr in cookie:
                parts[attr] = cookie[attr].value
        return parts

    def get_form_data( self, data ):
        form_data = {}
        post = urllib.unquote( data.split('\r\n')[-1] ).decode('utf8')
        try:
            form_data = dict([p.split('=') for p in post.split('&')])
        except:
            form_data = {}
        return form_data
 
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
        #print "writing_to: ", write_to
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
        msg_length = sock.recv(15).strip()
        if not msg_length:
            return False
        elif 'GET' in msg_length:
            return msg_length + sock.recv(4048).strip()
        elif 'POST' in msg_length:
            return msg_length + sock.recv(4048).strip()
        else:
            msg_length = int(msg_length)
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
        if os.path.isfile( file_path ):
            file_dir, file_name = self.dir_and_name( file_path )
            file_packet = {
                'type': 'complete_file',
                'name': file_name,
                'file_dir': file_dir.replace('\\','/'),
                'created': str(datetime.fromtimestamp( os.path.getctime(file_path) )),
                'modified': str(datetime.fromtimestamp( os.path.getmtime(file_path) )),
                'modified_by': self.username,
                'modified_on': socket.gethostname()
                }
            if contents:
                try:
                    with open( file_path, 'rb' ) as file_contents:
                        file_packet['contents'] = base64.b64encode(''.join(file_contents))
                except Exception, e:
                    print "[ ERROR ] File not found: ", file_dir, file_name
                    return False
            if make_json:
                file_packet = json.dumps( file_packet )
            if key:
                pass
                #file_packet = self.encode( key, file_packet )
            return file_packet
        else:
            print "Couldn't find ", file_path
            return False
 
    def unpack_packet( self, packet, key=False ):
        if key:
            pass
            #packet = self.decode( key, packet )
        packet = json.loads( packet )
        if packet['type'] == "complete_file":
            try:
                packet['contents'] = base64.b64decode(packet['contents'])
            except:
                pass
        return packet
 
    def send_file( self, file_path=False, file_packet=False ):
        if not file_packet:
            file_packet = self.create_file_packet( file_path, str(datetime.utcnow())[:7] )
        if file_packet:
            res = self.send( file_packet )
            if res and res[:5] != "ERROR":
                return res
            else:
                return False
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
        sql = pysync_sql( dbname=self.pysync_dir+'.pysyncfiles' )
        file_packet = self.create_file_packet( file_path, contents=False, make_json=False )
        # Dont check the database file
        if (os.name == 'nt' and sql.dbname.split('\\')[-1] == file_packet['name']) or (sql.dbname.split('/')[-1] == file_packet['name']) or ('.sync_with' == file_packet['name']):
            return False
        # Get the sql record for the file
        sql_record = sql.get_file( file_packet['file_dir'], file_packet['name'] )
        # No sql record, create one
        if not sql_record:
            sql.update_file( file_packet['file_dir'], file_packet )
            print "Created sql", file_packet['name']
        # Sql record present
        else:
            # Make datetime objects for compairison
            sql_record['modified'] = datetime.strptime(sql_record['modified'].split('.')[0], "%Y-%m-%d %H:%M:%S")
            file_packet['modified'] = datetime.strptime(file_packet['modified'].split('.')[0], "%Y-%m-%d %H:%M:%S")
            # Check if the actual file was modified more recently
            if sql_record['modified'] < file_packet['modified']:
                print "\t", sql_record['modified'], "<",file_packet['modified']
                sql.update_file( file_packet['file_dir'], file_packet )
                print "Updated sql", file_packet['name']
        sql.con.close()

    def get_server_updates( self, server_props ):
        sql = pysync_sql( dbname=self.real_path( '/','.pysyncfiles') )
        if server_props:
            self.pysync_server_address = server_props['address']
            self.pysync_server_port = server_props['port']
        # get the server's sql database
        packet = json.dumps( {'type': 'get_db'} )
        #packet = self.encode( str(datetime.utcnow())[:7], packet )
        response = self.send( packet )
        if response:
            sync_with_path = self.real_path( '/','.sync_with')
            if os.path.exists( sync_with_path ):
                os.remove( sync_with_path )
            sync_with = self.unpack_packet( response, str(datetime.utcnow())[:7] )
            sync_with['name'] = '.sync_with'
            self.write_file( sync_with )
            sync_with = pysync_sql( dbname=sync_with_path )
            # Get all files from each
            server_files = sync_with.all_files()
            myfiles = sql.all_files()
            for my_file in myfiles:
                try:
                    server_file = sync_with.get_file( my_file['file_dir'], my_file['name'] )
                    my_file['file_path'] = self.real_path( my_file['file_dir'], my_file['name'] )
                    # Check if the file is on the server
                    if server_file:
                        my_file['modified'] = datetime.strptime(my_file['modified'].split('.')[0], "%Y-%m-%d %H:%M:%S")
                        server_file['modified'] = datetime.strptime(server_file['modified'].split('.')[0], "%Y-%m-%d %H:%M:%S")
                        # Check if our version is newer than the servers
                        if server_file['modified'] < my_file['modified']:
                            # Get back the time the file was writin on server and set that in our db
                            print "Sent updated: ", my_file['name'], my_file['modified'],
                            update_file = self.create_file_packet( my_file['file_path'] )
                            if not update_file:
                                sql.delete_file( my_file['file_dir'], my_file['name'] )
                                print "[  LOG  ] Deleted file: ", my_file['file_dir'], my_file['name']
                                continue
                            update_file = self.send_file( file_packet=update_file )
                            update_file = self.unpack_packet( update_file, str(datetime.utcnow())[:7] )
                            sql.update_file( update_file['file_dir'], update_file )
                            print "\n\trecived at ", update_file['modified'].split('.')[0]
                            update_file = sql.get_file( update_file['file_dir'], update_file['name'] )
                            print "Local sql record is now at ", update_file['modified'].split('.')[0]
                    else:
                        # Server doesn't have the file
                        print "Sent original: ", my_file['name'], my_file['modified'],
                        # Get back the time the file was writin on server and set that in our db
                        update_file = self.create_file_packet( my_file['file_path'] )
                        if not update_file:
                            sql.delete_file( my_file['file_dir'], my_file['name'] )
                            print "[  LOG  ] Deleted file: ", my_file['file_dir'], my_file['name']
                            continue
                        update_file = self.send_file( file_packet=update_file )
                        update_file = self.unpack_packet( update_file, str(datetime.utcnow())[:7] )
                        sql.update_file( update_file['file_dir'], update_file )
                        print "\n\trecived at ", update_file['modified'].split('.')[0]
                        update_file = sql.get_file( update_file['file_dir'], update_file['name'] )
                        print "Local sql record is now at ", update_file['modified']
                except Exception, e:
                    print "[ ERROR ] While compairing local db to server: ", e
            sync_with.con.close()
            os.remove( sync_with_path )
            for server_file in server_files:
                try:
                    my_file = sql.get_file( server_file['file_dir'], server_file['name'] )
                    # Check if client has the file
                    if my_file:
                        my_file['modified'] = datetime.strptime(my_file['modified'].split('.')[0], "%Y-%m-%d %H:%M:%S")
                        server_file['modified'] = datetime.strptime(server_file['modified'].split('.')[0], "%Y-%m-%d %H:%M:%S")
                        # If it was modified elsewhere more recently and that place was not the clients computer
                        if my_file['modified'] < server_file['modified'] and server_file['modified_on'] != socket.gethostname():
                            print "\t", my_file['modified'],  "<",server_file['modified'], "\n\t",server_file['modified_on'], "!=",socket.gethostname()
                            # Request the file from the server
                            packet = json.dumps( {'type': 'get_file', 'file_dir': server_file['file_dir'], 'name': server_file['name'] } )
                            #packet = self.encode( str(datetime.utcnow())[:7], packet )
                            server_file = self.unpack_packet( self.send( packet ), str(datetime.utcnow())[:7] )
                            self.write_file( server_file )
                            # Set the date to after it was finished being writin
                            server_modified_time = server_file['modified']
                            server_file['modified'] = str(datetime.now())
                            # Update the sql for the file
                            sql.update_file( server_file['file_dir'], server_file )
                            # Send back to the server to tell it when our file was writen
                            del server_file['contents']
                            server_file['modified_on'] = socket.gethostname()
                            server_file['type'] = 'update_sql'
                            server_file['modified'] = server_modified_time
                            updated_server_file = json.dumps( server_file )
                            #updated_server_file = self.encode( str(datetime.utcnow())[:7], updated_server_file )
                            self.send( updated_server_file )
                            print "Updated from server ", server_file['name'], server_file['modified_on']
                    else:
                        print "\tLocal version not present"
                        # Request the file from the server
                        packet = json.dumps( {'type': 'get_file', 'file_dir': server_file['file_dir'], 'name': server_file['name'] } )
                        #packet = self.encode( str(datetime.utcnow())[:7], json.dumps(packet) )
                        server_file = self.unpack_packet( self.send( packet ), str(datetime.utcnow())[:7] )
                        self.write_file( server_file )
                        # Set the date to after it was finished being writin
                        server_modified_time = server_file['modified']
                        server_file['modified'] = str(datetime.now())
                        # Update the sql for the file
                        sql.update_file( server_file['file_dir'], server_file )
                        # Send back to the server to tell it when our file was writen
                        del server_file['contents']
                        server_file['modified_on'] = socket.gethostname()
                        server_file['modified'] = server_modified_time
                        server_file['type'] = 'update_sql'
                        updated_server_file = json.dumps( server_file )
                        #updated_server_file = self.encode( str(datetime.utcnow())[:7], updated_server_file )
                        self.send( updated_server_file )
                        print "Created from server ", server_file['name'], server_file['modified_on']
                except Exception, e:
                    print "[ ERROR ] While compairing server db to local: ", e
            sql.con.close()

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
        if os.name != "nt":
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

    def add_user( self, username ):
        sql = pysync_sql( dbname=self.real_path('/','.pysyncfiles') )
        with sql.con:
            cur = sql.con.cursor()
            if sql.exists( 'pysync_users', 'username', username ):
                cur.execute('INSERT INTO pysync_users(username, password, pysync_key) VALUES( ?, ?, ? )', ( username, getpass.getpass('Password for \"' + username + '\": '), socket.gethostname() ) )
                print 'Created user: \"' + username + '\"'
            else:
                print 'User: \"' + username + '\" ' + 'already exists'
        sql.con.commit()
        sql.con.close()

class SSLTCPServer(SocketServer.TCPServer):
    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        """Constructor. May be extended, do not override."""
        SocketServer.TCPServer.__init__(self, server_address, RequestHandlerClass, False)

        key_dir = os.path.dirname(__file__)
        key_file = os.path.join(key_dir, 'server.key')
        cert_file = os.path.join(key_dir, 'server.crt')

        self.socket = ssl.wrap_socket(self.socket, keyfile=key_file, certfile=cert_file, cert_reqs=ssl.CERT_NONE)

        if bind_and_activate:
            self.server_bind()
            self.server_activate()

class pysync_connection_handler(SocketServer.BaseRequestHandler):
    def handle(self):
        server = pysync_server()
        try:
            message = server.recv_msg( self.request )
            try:
                response = server.handle_input( message )
                try:
                    self.request.sendall( response )
                except Exception, e:
                    print "[ ERROR ] Sending response: ", e
                    traceback.print_exc()
            except Exception, e:
                response = "[ ERROR ] Creating response: ", e
        except Exception, e:
            print "[ ERROR ] Reciving message: ", e

class pysync_connection_error(Exception):
    def __init__(self, value, function):
        self.value = value
        self.function = function
    def __str__(self):
        return repr(self.value)

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
    server.socket_server = SSLTCPServer((server.my_address, server.my_port), pysync_connection_handler)
    server.socket_server.serve_forever()
 
def watch( watch_host, watch_lock ):
    while True:
        if watch_host.poll():
            change = watch_host.recv()
        else: change = False
        if change == 'CHANGING':
            time.sleep(5)
            continue
        elif change:
            server.pysync_server_address = change['address']
            server.pysync_server_port = change['port']
        if os.path.isdir( server.pysync_dir ):
            try:
                server.scan_dir( server.pysync_dir )
            except Exception, e:
                print e
                traceback.print_exc()
                try:
                    watch_host.send( e.function )
                except:
                    pass
                time.sleep(5)
                continue
        else:
            os.makedirs( server.pysync_dir )
        try:
            server.get_server_updates( change )
        except Exception, e:
            print e
            traceback.print_exc()
            try:
                watch_host.send( e.function )
            except:
                pass
            time.sleep(5)
            continue
        time.sleep(5)

def set_host_parms( host=False ):
    if not host:
        host = raw_input('Host (if this is the host type \'me\'): ')
    error = True
    while error:
        if host == 'me':
            server.is_host(True)
        else:
            try:
                if ':' not in host:
                    host = { 'address': host, 'port': 3639 }
                else:
                    host = { 'address': host.split(':')[0], 'port': int(host.split(':')[1]) }
            except:
                print "[  FAIL ] Host in form of address:port, default port is 3639"
            try:
                server.change_host( host )
                error = False
            except Exception, e:
                print "[  FAIL ] Failed to connect: ", e
                host = raw_input('Host (if this is the host type \'me\'): ')

def changing_server_address( pipe, kill_me ):
    while True:
        pipe.send( 'CHANGING' )
        if kill_me.poll() and kill_me.recv() is True:
            return True
        time.sleep(5)

def signal_handler(signal, frame):
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
server = pysync_server()

parser = argparse.ArgumentParser()
parser.add_argument("--log", help="Logs all actions of server and connections")
parser.add_argument("--port", help="Sets this nodes port if it's the server")
parser.add_argument("--server", help="Sets this nodes server")
parser.add_argument("--add_user", help="Adds a user")
args = parser.parse_args()

if __name__ == '__main__':
    args = parser.parse_args()
    if args.add_user:
        server.add_user( args.add_user )
        sys.exit(0)
    if args.port:
        server.my_port = int( args.port )
    freeze_support()
    server.start()
    if args.server:
        set_host_parms( args.server )
    else:
        set_host_parms()
    while True:
        if server.change_host_pipe.poll():
            res = server.change_host_pipe.recv()
            try:
                if res['address']:
                    server.change_host_pipe.send( res )
            except:
                kill_it, kill_me = Pipe()
                changing = Process( target=changing_server_address, args=(server.change_host_pipe, kill_me,) )
                changing.start()
                res()
                kill_it.send(True)
                server.change_host_pipe.recv()
