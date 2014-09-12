PySync
======

Syncs files over local networks or to server with accessible port always keeping one node as the server.
If the server node fails all node got ot the next server in the queue.

To use you first have to generate the SSL and key files, input passwords and info as prompted
```
openssl genrsa -des3 -out server.orig.key 2048
openssl rsa -in server.orig.key -out server.key
openssl req -new -key server.key -out server.csr
openssl x509 -req -days 365 -in server.csr -signkey server.key -out server.crt
```

|Contains|To Do|Bugs|
|---|---|---|
| Web viewer| Server Queue| Files transfer mulitiple times|
| Syncing|| Some downloads (encoding issues)|
| SSL|||
| Downloads||
| Sign in||
