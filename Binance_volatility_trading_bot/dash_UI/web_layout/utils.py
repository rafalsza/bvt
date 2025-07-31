def color_performance(column):
    """
    color values in given column using green/red based on value>0
    Args:
        column:

    Returns:

    """
    color = "success" if column > 0 else "danger"
    return f"color: {color}"


def money_color(value):
    if value < 0:
        color = "danger"
    elif value > 0:
        color = "success"
    else:
        color = "white"
    return color


def color_negative_values(val):
    color = 'danger' if val < 0 else 'success'
    return 'color: %s' % color


def gray_background(s):
    return ['background-color: #333333' if i % 2 else '' for i in range(len(s))]
