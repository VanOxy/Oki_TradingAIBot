function cleanText(text) {
  if (!text || typeof text !== 'string') {
    return '';
  }
  return text.replace(/[^\w\s\d.%:(),#=-]/g, '').trim();
}

function parseTgNotification(text) {
  const cleanedText = cleanText(text);
  const lines = cleanedText.split('\n').map(line => line.trim()).filter(line => line);
  
  let token = null;
  let exchange = null;
  let openInterest = null;
  let volume = null;
  let trades8h = null;
  let oiChange4h = null;
  let coinChange24h = null;
  let notificationsCount8h = null;

  if (lines[0] !== '8 HOUR REPORT') {
    token = lines[0];
    exchange = lines[1].replace('#', '');
    openInterest = lines[3].split(' ')[2].replace('%', '');
    volume = lines[4].split(' ')[2].replace('%', '');
    if(exchange == 'Binance'){
      trades8h = lines[5].split(' ')[2];
      oiChange4h = lines[6].split('=')[1].replace('%', '');
      coinChange24h = lines[7].split('=')[1].replace('%', '');
      notificationsCount8h = lines[8].split(' ')[1];
    } else {
      oiChange4h = lines[5].split('=')[1].replace('%', '');
      coinChange24h = lines[6].split('=')[1].replace('%', '');
      notificationsCount8h = lines[7].split(' ')[1];
    }
  }

  const data = {
    token: token,
    exchange: exchange,
    openInterest: openInterest,
    volume: volume,
    trades8h: trades8h,
    oiChange4h: oiChange4h,
    coinChange24h: coinChange24h,
    notificationsCount8h: notificationsCount8h,
  };

  return data;
}

function _parseTg1hReport(text) {
  const cleaned = cleanText(text);
  const lines = cleaned
    .split('\n')
    .map(l => l.trim())
    .filter(Boolean);

  const indexByToken = new Map(); // token -> index
  const order = [];

  for (const line of lines) {
    // пропускаем заголовок/футер вида "8 HOUR REPORT"
    if (/^8 HOUR REPORT$/i.test(line)) continue;

    // пример строки после cleanText:
    // "31  #FORTHUSDT  Day:14,12:53"
    const m = line.match(/^(\d+)\s+.*?#([A-Z0-9]+)\b/i);
    if (!m) continue;

    const idx = Number(m[1]);
    const token = m[2].toUpperCase();

    if (!indexByToken.has(token)) {
      indexByToken.set(token, idx);
      order.push(token);
    } else if (idx > indexByToken.get(token)) {
      indexByToken.set(token, idx);
    }
  }

  return order.map(t => ({ token: t, index: indexByToken.get(t) }));
}

// если нужно сразу объект-словарь { TOKEN: index, ... }:
function parseTg1hReportDict(text) {
  const arr = _parseTg1hReport(text);
  const out = {};
  for (const { token, index } of arr) out[token] = index;
  return out;
}


export { parseTgNotification, parseTg1hReportDict};