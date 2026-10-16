import streamlit as st


def color_performance(column):
    """
    color values in given column using green/red based on value>0
    Args:
        column:

    Returns:

    """
    color = "green" if column > 0 else "red"
    return f"color: {color}"


def money_color(value):
    if value < 0:
        color = "red"
    elif value > 0:
        color = "green"
    else:
        color = "gray"
    return color


def color_negative_values(val):
    color = 'red' if val < 0 else 'green'
    return 'color: %s' % color


def gray_background(s):
    return ['background-color: #333333' if i % 2 else '' for i in range(len(s))]
