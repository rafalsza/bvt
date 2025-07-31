#!/bin/bash

# Start the first process
python BinanceDetectMoonings.py &
# Start the second process
(cd dash_UI ; python dash_app.py)
