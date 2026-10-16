FORMAT___PARAMS_VALUE_ = "d3.format('.2%')(params.value/100)"
PARAMS_VALUE_ = "d3.format('$,.6f')(params.value)"
cellsytle_jscode = """
function(params) {
    if (params.value <= 0) {
        return {
            'color': 'red'
        }
    } else {
        return {
            'color': 'green'
        }
    }
};
"""


columnDefs = [
    {
        "headerName": "Id",
        "field": "id",
        "width": 50,
        "filter": False,
    },
    {
        "headerName": "Buy Time",
        "field": "buy_time",
        "type": "dateColumn",
        "minWidth": 150,
    },
    {
        "headerName": "Symbol",
        "field": "symbol",
        "cellRenderer": "coin_page_link",
    },
    {
        "headerName": "Amount",
        "field": "volume",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": "d3.format('.6f')(params.value)"},
        "cellRenderer": "agAnimateShowChangeCellRenderer",
    },
    {
        "headerName": "Bought At",
        "field": "bought_at",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": PARAMS_VALUE_},
        "cellRenderer": "agAnimateShowChangeCellRenderer",
    },
    {
        "headerName": "Now At",
        "field": "now_at",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": PARAMS_VALUE_},
        "cellRenderer": "agAnimateShowChangeCellRenderer",
    },
    {
        "headerName": "Change %",
        "field": "change_perc",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": FORMAT___PARAMS_VALUE_},
        "maxWidth": 200,
        "cellClassRules": {
            # apply background color danger to <=0
            "bg-danger": "params.value <= 0",
            # apply background color success  to >0
            "bg-success text-dark": "params.value > 0",
        }
        # "valueFormatter": "value.toPrecision(3)",
    },
    {
        "headerName": "Profit $",
        "field": "profit_dollars",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": PARAMS_VALUE_},
        "aggFunc": "sum",
        "cellRenderer": "agAnimateShowChangeCellRenderer",
    },
    {
        "headerName": "TP %",
        "field": "tp_perc",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": FORMAT___PARAMS_VALUE_},
        "cellRenderer": "agAnimateShowChangeCellRenderer",
    },
    {
        "headerName": "SL %",
        "field": "sl_perc",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": FORMAT___PARAMS_VALUE_},
        "cellRenderer": "agAnimateShowChangeCellRenderer",
    },
    {
        "headerName": "Time held",
        "field": "time_held",
    },
    {
        "headerName": "Buy Signal",
        "field": "buy_signal",
    },
]

defaultColDef = {
    "filter": True,
    "resizable": True,
    "sortable": True,
    "editable": False,
    "floatingFilter": True,
}

cellStyle = {
    "styleConditions": [
        {
            "condition": "columnDefs.field == 'change_perc'",
            "style": {"backgroundColor": "green"},
        },
    ]
}

dashGridOption_closed_trades = {
    "rowSelection": "single",
    "headerHeight": 30,
    "pagination": True,
    "paginationPageSize": 10,
}

columnDefs_closed_trades = [
    {
        "headerName": "Id",
        "field": "id",
        "width": 50,
        "filter": False,
    },
    {
        "headerName": "Buy Time",
        "field": "buy_time",
        "type": "dateColumn",
        "minWidth": 150,
    },
    {
        "headerName": "Symbol",
        "field": "symbol",
        "cellRenderer": "coin_page_link",
    },
    {
        "headerName": "Amount",
        "field": "volume",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": "d3.format('.6f')(params.value)"},
        "cellRenderer": "agAnimateShowChangeCellRenderer",
    },
    {
        "headerName": "Bought At",
        "field": "bought_at",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": PARAMS_VALUE_},
        "cellRenderer": "agAnimateShowChangeCellRenderer",
    },
    {
        "headerName": "Sold At",
        "field": "sold_at",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": PARAMS_VALUE_},
        "cellRenderer": "agAnimateShowChangeCellRenderer",
    },
    {
        "headerName": "Change %",
        "field": "change_perc",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": FORMAT___PARAMS_VALUE_},
        "maxWidth": 200,
        "cellClassRules": {
            # apply background color danger to <=0
            "bg-danger": "params.value <= 0",
            # apply background color success  to >0
            "bg-success text-dark": "params.value > 0",
        }
        # "valueFormatter": "value.toPrecision(3)",
    },
    {
        "headerName": "Profit $",
        "field": "profit_dollars",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": PARAMS_VALUE_},
        "aggFunc": "sum",
        "cellRenderer": "agAnimateShowChangeCellRenderer",
    },
    {
        "headerName": "TP %",
        "field": "tp_perc",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": FORMAT___PARAMS_VALUE_},
        "cellRenderer": "agAnimateShowChangeCellRenderer",
    },
    {
        "headerName": "SL %",
        "field": "sl_perc",
        "type": ["numericColumn", "numberColumnFilter", "customNumericFormat"],
        "valueFormatter": {"function": "d3.format('.2%')(params.value/100)"},
        "cellRenderer": "agAnimateShowChangeCellRenderer",
    },
    {
        "headerName": "Sell Time",
        "field": "sell_time",
        "type": "dateColumn",
    },
    {
        "headerName": "Time held",
        "field": "time_held",
    },
    {
        "headerName": "Buy Signal",
        "field": "buy_signal",
    },
    {
        "headerName": "Sell Reason",
        "field": "sell_reason",
    },
]
