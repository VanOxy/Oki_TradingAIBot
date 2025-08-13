const buffer = {
  binance: [],
  coinglass: [],
  MAX_LEN: 100,
};

function add(source, data) {
  if (!buffer[source]) return;
  buffer[source].push(data);
  if (buffer[source].length > buffer.MAX_LEN) {
    buffer[source].shift();
  }
}

module.exports = { buffer, add };