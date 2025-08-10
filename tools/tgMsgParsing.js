function cleanText(text) {
  if (!text || typeof text !== 'string') {
    return '';
  }
  return text.replace(/[^\w\s\d.%:(),#=-]/g, '').trim();
}

function parseNotification(text) {
  const cleanedText = cleanText(text);
  const lines = cleanedText.split('\n').map(line => line.trim()).filter(line => line);
  
  let pair = null;
  let exchange = null;
  let openInterest = null;
  let volume = null;
  let trades8h = null;
  let oiChange4h = null;
  let coinChange24h = null;
  let tradesCount8h = null;

  if (lines[0] !== '8 HOUR REPORT') {
    pair = lines[0];
    exchange = lines[1].replace('#', '');
    openInterest = lines[3].split(' ')[2].replace('%', '');
    volume = lines[4].split(' ')[2].replace('%', '');
    if(exchange == 'Binance'){
      trades8h = lines[5].split(' ')[2];
      oiChange4h = lines[6].split('=')[1].replace('%', '');
      coinChange24h = lines[7].split('=')[1].replace('%', '');
      tradesCount8h = lines[8].split(' ')[1];
    } else {
      oiChange4h = lines[5].split('=')[1].replace('%', '');
      coinChange24h = lines[6].split('=')[1].replace('%', '');
      tradesCount8h = lines[7].split(' ')[1];
    }
  }

  const data = {
    pair: pair,
    exchange: exchange,
    openInterest: openInterest,
    volume: volume,
    trades8h: trades8h,
    oiChange4h: oiChange4h,
    coinChange24h: coinChange24h,
    tradesCount8h: tradesCount8h,
  };

  return data;
}

module.exports = { parseNotification };
