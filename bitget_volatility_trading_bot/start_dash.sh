#!/bin/bash

# Start the first process
python bitget_volatility_bot.py &
# Start the second process
(cd dash_UI ; python dash_app.py)
