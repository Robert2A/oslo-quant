import sys
from PyQt5 import QtWidgets, QtGui, QtCore
import pyqtgraph as pg
from setproctitle import setproctitle
import datetime
import numpy as np
import signal


class LinkedPlotWidget(pg.GraphicsLayoutWidget):
    """Widget for stacking several plots with linked x-axes vertically"""

    mouse_pressed_signal = QtCore.pyqtSignal()
    mouse_released_signal = QtCore.pyqtSignal()

    def __init__(self, inputs, window_title=''):
        """
        args:
           inputs: list of tuples: (numpy_array, data_column_name, plot_title).
                   It is assumed that numpy_array['date'] exists.
           window_title(str): Title of the window
        """
        super().__init__()

        self.setWindowTitle(window_title)

        # label for showing y/x values for crosshair
        self.label = pg.LabelItem(justify='left')
        self.label.setVisible(True)
        self.addItem(self.label)

        # strings for construction self.label, used by self.update_label()
        self.cursor_x_label = ''
        self.cursor_y_label = ''

        # install an event filter to detect that the mouse leaves the widget
        self.installEventFilter(self)

        self.plot_row_counter = 1
        self.first_plot = None
        self.plots = {}
        self.latest_plot = None
        self.first_plot = None

    def add_plot(self, plot_title):

        plot = self.addPlot(row=self.plot_row_counter, col=0)

        self.plot_row_counter += 1

        # some predefined colors that aren't too ugly
        plot.nice_colors = [(255, 255, 255),
                            (162, 195, 249),
                            (132, 255, 206),
                            (243, 252, 148),
                            (255, 145, 145)]

        # set fixed tick label width, to that the plots align vertically
        plot.getAxis('left').setWidth(60)

        # crosshair
        v_line = pg.InfiniteLine(angle=90, movable=False)
        h_line = pg.InfiniteLine(angle=0, movable=False)
        plot.addItem(v_line, ignoreBounds=True)
        plot.addItem(h_line, ignoreBounds=True)

        # TODO: should we make a function out of this?
        # vertical line for showing the time position of an event
        #event_line = pg.InfiniteLine(angle=90, movable=False)
        #event_line.setPen(QtGui.QColor(168, 34, 3))
        #plot.addItem(event_line, ignoreBounds=True)
        #plot.event_line = event_line

        plot.scene().sigMouseMoved.connect(self.mouse_moved)

        # store references to these things in the PlotView object
        plot.v_line = v_line
        plot.h_line = h_line

        # the text responsible for showing the y value where the vertical line is
        value_text = pg.TextItem(anchor=(0.5, 0))
        value_text.setPos(92, 0)
        value_text.setParentItem(plot)
        plot.value_text = value_text

        # hide meaningless x-axis ticks
        plot.getAxis('bottom').setTicks([])

        plot.name = plot_title

        # each plot must have a unique identifier
        if plot.name in self.plots:
            unique_name = id(plot)
        else:
            unique_name = plot.name

        self.plots[unique_name] = plot
        self.latest_plot = plot
        if self.first_plot is None:
            self.first_plot = plot

    def add_subplot(self, numpy_array, y_axis_name):

        if self.latest_plot is None:
            raise KeyError("add_plot() hasn't been called yet")

        # if the numpy 'data' column is a Python object, assume it's datatime.date
        if numpy_array['date'].dtype == np.dtype('O'):

            # construct a new array with only room for the date column converted to timestamp
            date_array = np.empty(shape=(len(numpy_array['date'])),
                                  dtype=[('date', 'f8')])

            # fill the new array
            for i, d in enumerate(numpy_array['date']):

                # convert the datetime.date to a timestamp
                dt = datetime.datetime(d.year, d.month, d.day)
                date_array[i] = dt.timestamp(),

        # assume that numpy_array['date'] is an epoch timestamp
        else:
            # use the array as-is because there's no need to convert the date column
            date_array = numpy_array

        try:
            color = self.latest_plot.nice_colors.pop(0)
        except IndexError:
            raise IndexError(
                "All predefined colors have been used for this plot")

        # create the subplot
        subplot = self.latest_plot.plot(row=self.plot_row_counter,
                                        col=0,
                                        pen=color,
                                        y=numpy_array[y_axis_name],
                                        x=date_array['date'])
        subplot.parent_plot = self.latest_plot

        unique_name = subplot.parent_plot.name + "_" + y_axis_name

        # the subplot display name will appear in the legend
        if(self.latest_plot.name == ''):
            subplot.display_name = y_axis_name
        else:
            subplot.display_name = unique_name

        # check that there doesn't exist a subplot with this name
        for subplot in subplot.parent_plot.dataItems:
            if subplot.name == unique_name:
                raise ValueError('subplot name "' +
                                 unique_name + "' already exists")

        # set the subplot name
        subplot.name = unique_name

        # connect the mouse moved listener
        subplot.scene().sigMouseMoved.connect(self.mouse_moved)

        # link the y-axes of the time series in this plot
        box = subplot.getViewBox()
        box.setYLink(subplot.parent_plot)

        # link the x-axes of all plots
        box = subplot.getViewBox()
        box.setXLink(self.first_plot)

    def show(self):
        super().show()

    def remove_plot(self, plot_title):
        pl = self.plots.pop(plot_title)
        self.removeItem(pl)

    def remove_all_plots(self):
        for pl_title in list(self.plots):
            self.remove_plot(pl_title)
        self.first_plot = None

    def add_marker(self, plot_title, y_axis_name, date, angle=-90, text="", color='blue'):
        """
        Add a marker to a plot

        Args:
           plot_title (str): The name of the plot
           y_axis_name(str): The name of the subplot to attach the marker to
           date (datetime.date): x-axis date to add a marker to
           angle (int): Angle of the arrow marker. -90 is top down.
           color (str): 'blue', 'green', or 'red'

        Raises:
           IndexError: If the date isn't present in the data set
           KeyError: If the plot or subplot isn't found
        """
        # get the plot
        pl = self.get_plot(plot_title)

        # try to convert date/datetime to timestamp
        try:
            timestamp = datetime.datetime(
                date.year, date.month, date.day).timestamp()
        except:
            # try to use the the value as is
            timestamp = date

        ld = self.get_subplot(plot_title, y_axis_name)

        # get the index containing the nearest timestamp value for this x position
        x_data = ld.getData()[0]
        matches = np.where(x_data == timestamp)[0]

        # if this happens, there is something wrong with the data
        if len(matches) > 1:
            raise Exception(
                "There are more than one x index containing this timestamp")

        elif len(matches) < 1:
            raise IndexError("The timestamp " + str(date) +
                             " wasn't found in the data set")

        else:
            x_index = matches[0]

        # a curvepoint refers to an xy point on the plot line
        curvePoint = pg.CurvePoint(ld, index=x_index)

        # background color
        if color == 'blue':
            brush = (0, 0, 255, 110)  # blue
        elif color == 'green':
            brush = (0, 255, 0, 110)  # green
        elif color == 'red':
            brush = (255, 0, 0, 150)  # red
        else:
            raise Exception("Color '%s' isn't implemented" % color)

        # create an arrow
        arrow = pg.ArrowItem(angle=angle, brush=brush)
        arrow.setParentItem(curvePoint)

        if text != "":

            # split into <span> tags
            spans = []
            for line in text.split("\n"):
                spans.append(
                    '<span style="color: #FF0; font-size: 14pt;">%s</span>' % line)

            # create html text box
            html = '<div style="text-align: center">%s</div>' % "<br>".join(
                spans)

            # Adjust the y anchor point to the number of lines in the text box.
            # I don't know how to so this properly.
            if len(spans) == 1:
                anchor_y = 1.8
            elif len(spans) == 2:
                anchor_y = 1.45
            elif len(spans) == 3:
                anchor_y = 1.32
            elif len(spans) == 4:
                anchor_y = 1.25
            elif len(spans) == 5:
                anchor_y = 1.2
            else:
                raise Exception(
                    "%d line count text box isn't implemented" % anchor_y)

            # create the text box and attach it to the curve point
            text = pg.TextItem(html=html, anchor=(
                0.5, anchor_y), border='w', fill=brush)
            text.setParentItem(curvePoint)

        pl.addItem(curvePoint)

    def leaveEvent(self, event):
        """Called when the mouse leaves this widget"""
        self.crosshair_visible(False)
        self.hide_label()

    def vertical_line(self, timestamp):
        """Draw a vertical line at timestamp"""

        for plot in self.plots.values():
            # get a reference to the x-axis numpy data (time column)
            time_col = plot.dataItems[0].xData

            plot.event_line.setPos(timestamp)
            plot.event_line.setVisible(True)

    def crosshair_visible(self, true_or_false):
        """Set closshair visibility"""
        for pl in self.plots.values():
            pl.h_line.setVisible(true_or_false)
            pl.v_line.setVisible(true_or_false)

    def update_label(self, cursor_x, cursor_y):
        """Change the labels. Arguments are floats"""
        timestamp = datetime.date.fromtimestamp(cursor_x)
        timestamp_str = timestamp.strftime("%Y-%m-%d")
        text = "<span>crosshair</span>: " \
               "<span style='color: Aqua'>x=%s</span>, " \
               "<span style='color: GreenYellow'>y=%s</span>" % (
                   timestamp_str, str(round(cursor_y, 4)))
        self.label.setText(text)

    def hide_label(self):
        """Hide labels"""
        self.label.setText('')

    def mouse_moved(self, pos):
        """Callback when mouse is moved"""
        mouse_is_over_a_plot = False

        for pl in self.plots.values():
            # ignore plots that are invisible
            if not pl.isVisible():
                continue

            try:
                mousePoint = pl.vb.mapSceneToView(pos)
            except np.linalg.LinAlgError:
                # probably, the plot was replaced, causing this error
                return

            # if the mouse pointer is over this plot
            if pl.sceneBoundingRect().contains(pos):
                mouse_is_over_a_plot = True
                pl.h_line.setVisible(True)
                pl.h_line.setPos(mousePoint.y())
                self.update_label(cursor_x=mousePoint.x(),
                                  cursor_y=mousePoint.y())
            else:
                pl.h_line.setVisible(False)

            # set the position of the vertical line
            pl.v_line.setPos(mousePoint.x())

        # if the mouse pointer is over any of the plots
        if mouse_is_over_a_plot:

            for pl in self.plots.values():
                pl.v_line.setVisible(True)

                # get the x position of the vertical crosshair line
                x_mouse = mousePoint.x()

                text = ""

                # get the numpy arrays containing the x and y data for all subplots
                for subplot in pl.listDataItems():
                    data = subplot.getData()
                    x_data = data[0]
                    y_data = data[1]

                    # get the index containing the nearest timestamp value for this x position
                    x_index = (np.abs(x_data - x_mouse)).argmin()

                    # if the x index is at the min position
                    if x_index == 0:

                        # hide the text if the x position outside of the plot
                        if x_mouse < x_data[0]:
                            pl.value_text.setText("")

                    # if the x index is at the max position
                    elif x_index == len(x_data) - 1:

                        # hide the text if the x position outside of the plot
                        if x_mouse > x_data[-1]:
                            pl.value_text.setText("")

                    # if the x position is within the plot
                    else:
                        # get the y value
                        y = y_data[x_index]

                        color = subplot.opts['pen']

                        # set the y value at the vertical line on this plot at the x position
                        text += "<span style='color: rgb%s'>%s=%s</span><br>" % (
                            color, subplot.display_name, str(round(y, 4)))

                pl.value_text.setHtml(text)

        else:
            # hide the crosshair text
            self.hide_label()

            # hide the plot y value text
            for pl in self.plots.values():
                pl.value_text.setText("")

    def eventFilter(self, widget, event):
        # if the mouse pointer exits the widget
        if event.type() == QtCore.QEvent.MouseMove:
            self.hide_label()
            for pl in self.plots.values():
                pl.h_line.setVisible(False)
                pl.v_line.setVisible(False)
        return False

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.mouse_pressed_signal.emit()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.mouse_released_signal.emit()

    def get_plot(self, plot_title):
        try:
            return self.plots[plot_title]
        except KeyError:
            raise KeyError('Plot with title "' + plot_title + '" not found')

    def get_subplot(self, plot_title, y_axis_name):

        # name of the subplot to look for
        name = plot_title + "_" + y_axis_name

        # find the parent plot
        pl = self.get_plot(plot_title)

        # find the subplot
        for subplot in pl.listDataItems():
            if subplot.name == name:
                return subplot

        raise KeyError('Could not find a subplot named "' + name + "'")


class LinkedPlot():
    """
    Create a windows of linked plots using LinkedPlotWidget

    args:
        window_title(str): Title of the window
    """

    def __init__(self, window_title=""):
        setproctitle("oslo-quant-linkedplot")
        self.app = QtWidgets.QApplication(sys.argv)

        self.linked_plot_widget = LinkedPlotWidget(window_title)

    def add_plot(self, plot_title=""):
        self.linked_plot_widget.add_plot(plot_title)

    def add_subplot(self, numpy_array, y_axis_name):
        self.linked_plot_widget.add_subplot(numpy_array, y_axis_name)

    def show(self):

        # install signal handler
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        self.linked_plot_widget.show()
        sys.exit(self.app.exec_())

    def add_marker(self, plot_title, y_axis_name, date,
                   angle=-90, text="", color='blue'):
        self.linked_plot_widget.add_marker(
            plot_title, y_axis_name, date, angle, text, color)
