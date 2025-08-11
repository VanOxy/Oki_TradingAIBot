const axios = require('axios');

async function getLiquidations(symbol) {
    try {
        const response = await axios.get(`https://api.coin-glass.com/api/v1/liquidation`, {
            params: {
                symbol: symbol, // Например, BTCUSDT
            }
        });
        return response.data;
    } catch (error) {
        console.error("Error fetching liquidations:", error);
    }
}

getLiquidations('BTCUSDT').then(data => console.log(data));

async function getCVD(symbol) {
    try {
        const response = await axios.get(`https://api.coin-glass.com/api/v1/cvd`, {
            params: {
                symbol: symbol, // Например, BTCUSDT
            }
        });
        return response.data;
    } catch (error) {
        console.error("Error fetching CVD:", error);
    }
}

getCVD('BTCUSDT').then(data => console.log(data));

async function getAggregatedSpotCVD(symbol) {
    try {
        const response = await axios.get(`https://api.coin-glass.com/api/v1/aggregated_spot_cvd`, {
            params: {
                symbol: symbol, // Например, BTCUSDT
            }
        });
        return response.data;
    } catch (error) {
        console.error("Error fetching aggregated spot CVD:", error);
    }
}

getAggregatedSpotCVD('BTCUSDT').then(data => console.log(data));

async function getOpenInterest(symbol) {
    try {
        const response = await axios.get(`https://api.coin-glass.com/api/v1/open_interest`, {
            params: {
                symbol: symbol, // Например, BTCUSDT
            }
        });
        return response.data;
    } catch (error) {
        console.error("Error fetching open interest:", error);
    }
}

getOpenInterest('BTCUSDT').then(data => console.log(data));

