// Dependency-free HTTP and WebSocket echo for native Node 20 acceptance.
const http = require('node:http');
const crypto = require('node:crypto');
const fs = require('node:fs');
const version = fs.readFileSync(__dirname + '/fixture-version.txt', 'utf8').trim();
const server = http.createServer((req, res) => {
  res.writeHead(200, {'Content-Type': 'application/json'});
  res.end(JSON.stringify({status: 'ok', application: 'e2e-f059-node', version}));
});
server.on('upgrade', (req, socket) => {
  if (req.headers.upgrade?.toLowerCase() !== 'websocket' || req.headers['sec-websocket-version'] !== '13') return socket.destroy();
  const key = req.headers['sec-websocket-key'];
  if (!key || Buffer.from(key, 'base64').length !== 16) return socket.destroy();
  const accept = crypto.createHash('sha1').update(key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + '\r\n\r\n');
  let pending = Buffer.alloc(0);
  socket.on('data', (chunk) => {
    pending = Buffer.concat([pending, chunk]);
    while (pending.length >= 2) {
      const opcode = pending[0] & 15;
      let length = pending[1] & 127, offset = 2;
      if (!(pending[1] & 128) || (pending[0] & 112)) return socket.destroy();
      if (length === 127) return socket.destroy();
      if (length === 126) {
        if (pending.length < 4) return;
        length = pending.readUInt16BE(2); offset = 4;
      }
      if (pending.length < offset + 4 + length) return;
      const mask = pending.subarray(offset, offset + 4);
      const payload = Buffer.from(pending.subarray(offset + 4, offset + 4 + length));
      pending = pending.subarray(offset + 4 + length);
      for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
      if (opcode === 8) return socket.end(Buffer.from([136, 0]));
      if (![1, 9].includes(opcode)) return socket.destroy();
      const head = length < 126 ? Buffer.from([opcode === 9 ? 138 : 129, length]) : Buffer.from([opcode === 9 ? 138 : 129, 126, length >> 8, length & 255]);
      socket.write(Buffer.concat([head, payload]));
    }
  });
});
server.listen(Number(process.env.PORT || 8080), '0.0.0.0');
