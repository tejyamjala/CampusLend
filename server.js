const express = require('express');
const path = require('path');

const app = express();
const PORT = Number(process.env.PORT || 3000);
const publicDir = path.join(__dirname, 'public');

app.disable('x-powered-by');
app.use(express.json());
app.get('/health', (_req, res) => res.status(200).json({ ok: true, service: 'campusloop' }));
app.get('/api/status', (_req, res) => res.json({ mode: 'demo', message: 'CampusLoop demo workspace ready' }));
app.use(express.static(publicDir, { extensions: ['html'] }));
app.get('*', (_req, res) => res.sendFile(path.join(publicDir, 'index.html')));

app.listen(PORT, '0.0.0.0', () => {
  console.log(`CampusLoop listening on 0.0.0.0:${PORT}`);
});
