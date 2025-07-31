var dagfuncs = window.dashAgGridComponentFunctions = window.dashAgGridComponentFunctions || {};

dagfuncs.coin_page_link = function (params) {
    return React.createElement('a', {
    href: 'https://www.tradingview.com/chart/?symbol=BINANCE:' + params.value,
    target: params.value,
    className: 'text-info' // add a className attribute with value 'text-info'
    }, params.value)
}