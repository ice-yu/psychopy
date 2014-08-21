__author__ = 'Sol'
import numpy as np
from collections import deque
from psychopy.iohub.util import NumPyRingBuffer
from psychopy.iohub import EventConstants, DeviceEvent, print2err, Computer


# Event Filter / Translator / Parser Class Prototype

class DeviceEventFilter(object):
    """
    Base class for creating a filtered / processed event stream from
    a device's iohub events. Any device event filter class MUST use this
    class as the base class type.

    The following properties must be implemented by a DeviceEventFilter subclass:
        * filter_id
        * input_event_types

    The following methods must be implemented by a DeviceEventFilter subclass:
        * process

    The class __init__ can accept a set of kwargs, which will automatically be
    converted into class_instance.key = value attributes.

    """
    event_filter_id_index = DeviceEvent.EVENT_FILTER_ID_INDEX
    event_id_index = DeviceEvent.EVENT_ID_INDEX
    event_time_index = DeviceEvent.EVENT_HUB_TIME_INDEX

    def __init__(self, **kwargs):
        # _parent_device_type filled in by iohub
        self._parent_device_type = None
        # _filter_id filled in by iohub
        self._filter_key = None

        self._input_events = []
        self._output_events = []

        for key, value in kwargs.items():
            setattr(self, key, value)

        self._enabled = False

    @property
    def enable(self):
        return self._enabled

    @enable.setter
    def enable(self,v):
        self._enabled = v

    def getInputEvents(self):
        return self._input_events

    def clearInputEvents(self):
        self._input_events = []

    def reset(self):
        self._input_events = []
        self._output_events = []

    @property
    def filter_id(self):
        raise RuntimeError("filter_id property must be set by subclass.")

    @property
    def input_event_types(self):
        raise RuntimeError("input_event_types property must be set by subclass.")

        # Example:
        #
        # Request MouseMove events that have not been filtered (filter id 0):
        #
        # event_type_and_filter_ids = dict()
        # event_type_and_filter_ids[EventConstants.MOUSE_MOVE]=[0,]
        # return event_type_and_filter_ids

    def process(self):
        """
        *** This method must be implemented by the sub class. ***

        # Process / filter events.
        #
        # Called by the iohub server each time an iohub device
        # receives a new iohub event.
        #
        # Get new events to process by calling getInputEvents().
        # Add processed events that are ready to be output by iohub by
        # calling addOutputEvent(e).
        #
        # Optionally remove the input events processed so they are not
        # repeatedly retrieved using clearInputEvents(.
        #
        # The events returned by getInputEvents() are copies of the
        # original event lists, so it is fine to filter in place if desired.
        #
        # Each event passed to addOutputEvent() will have it's event_id and
        # filter_id updated appropriately; this is done for you.
        """
        raise RuntimeError("process method must be implemented by subclass.")

    def addOutputEvent(self, e):
        e[self.event_id_index] = Computer._getNextEventID()
        e[self.event_filter_id_index] = self.filter_id
        self._output_events.append(e)

    def _addInputEvent(self, evt):
        """
        Takes event from parent device for processing.
        """
        self._input_events.append(evt)
        self.process()

    def _removeOutputEvents(self):
        """
        Called by the the iohub Server when processing device events.
        """
        oevts = self._output_events
        self._output_events = []
        return oevts

####################### Device Event Field Filter Types ########################

class MovingWindowFilter(object):
    """
    Maintains a moving window of size 'length', for a specific event
    field value, given by 'event_field_name'. knot_pos defines where in the
    window the next filtered value should always be returned from.
    knot_pos can be an index between 0 - length-1, or a string constant:
        'center': use the middle value in the window. Window length must be odd.
        'latest': the value just added to the window is filtered and returned
        'oldest': the last value in the buffer is filtered and returned

    If the windowing buffer is full, a filtered value is returned when a
    value is added to the MovingWindow using MovingWindow.add.
    None is returned until the MovingWindow is full.

    The base class implements a moving window averaging filter, no weights.
    To change the filter used, extend this class and replace the filteredValue
    method.
    """
    def __init__(self, **kwargs):
        self._inplace = kwargs.get('inplace')
        knot_pos = kwargs.get('knot_pos')
        length = kwargs.get('length')
        event_type = kwargs.get('event_type')
        event_field_name = kwargs.get('event_field_name')
        if isinstance(knot_pos, basestring):
            if knot_pos == 'center' and length%2 == 0:
                raise ValueError("MovingWindow length must be odd for a centered knot_pos.")
            if knot_pos == 'center':
                self._active_index = length//2
            elif knot_pos == 'latest':
                self._active_index = 0
            elif knot_pos == 'oldest':
                self._active_index = length-1
            else:
                raise ValueError("MovingWindow knot_pos must be an index between 0 - length-1, or a string constantin ['center','latest','oldest']")
        else:
            if knot_pos < 0 or knot_pos >= length:
                raise ValueError("MovingWindow knot_pos must be between 0 and length-1.")
            self._active_index = knot_pos

        self._event_field_index = None
        self._events = None
        if event_type and event_field_name:
            self._event_field_index = EventConstants.getClass(event_type).CLASS_ATTRIBUTE_NAMES.index(event_field_name)
            self._events = deque(maxlen=length)

        self._filtering_buffer = NumPyRingBuffer(length)

    def filteredValue(self):
        """
        Returns a filtered value based on the data in the window. The base
        implementation returns the average value of the window values.
        Sub classes of MovingWindowFilter can implement their own filteredValue
        method so that different moving window filter types can be created.
        """
        return self._filtering_buffer.mean()

    def add(self, event):
        """
        Add the given iohub event ( in list form ) to the moving window.
        The value of the specified event attribute when the filter was
        created is what is used to calculate return values for the filter.

        If the window is full, this method returns an iohub event that has
        been filtered, and the filtered value of the field being filtered.
        """
        if isinstance(event, (list,tuple)):
            self._filtering_buffer.append(event[self._event_field_index])
            self._events.append(event)
            if self.isFull():
                if self._inplace:
                    self._events[self._active_index][self._event_field_index] = self.filteredValue()
                return self._events[self._active_index], self.filteredValue()
        else:
            self._filtering_buffer.append(event)
            if self.isFull():
                return None, self.filteredValue()

    def isFull(self):
        return self._filtering_buffer.isFull()

    def clear(self):
        self._filtering_buffer.clear()
        if self._events:
            self._events.clear()
# ------

class PassThroughFilter(MovingWindowFilter):
    """
    Returns the median value of the moving window. Length must be odd.
    """
    def __init__(self, **kwargs):
        kwargs['length'] = 1
        kwargs['knot_pos'] = 0
        MovingWindowFilter.__init__(self, **kwargs)

    def filteredValue(self):
        return self._filtering_buffer[0]

# ------

class MedianFilter(MovingWindowFilter):
    """
    Returns the median value of the moving window. Length must be odd.
    """
    def __init__(self, **kwargs):
        MovingWindowFilter.__init__(self, **kwargs)

    def filteredValue(self):
        return np.median(self._filtering_buffer.getElements())

# ------

class WeightedAverageFilter(MovingWindowFilter):
    """
    Returns the weighted average of the moving window. Window length is equal to
    len(weights). The weights array will be normalized using:

    weights = weights / numpy.sum(weights)

    before being used by the filter.
    """
    def __init__(self, **kwargs):
        weights = kwargs.get('weights')
        length = len(weights)
        kwargs['length'] = length
        MovingWindowFilter.__init__(self, **kwargs)
        weights = np.asanyarray(weights)
        self._weights = weights / np.sum(weights)

    def filteredValue(self):
        return np.convolve(self._filtering_buffer.getElements(), self._weights, 'valid')


# ------

class StampFilter(MovingWindowFilter):
    """
    Implements The Stampe Filter (written by Dave Stampe of SR Research).
    The filter has a window length of 3. If the window values (v1,v2,v3) are
    non monotonic, then the middle value is replaced by the mean of v1 and v3.
    Otherwise v2 is returned unmodified.

    level arg indicates how many iterations of the Stampe filter should be
    applied before starting to return filtered data. Default = 1.

    If levels = 2, then the filter would use data returned from a sub filter
    instance of the Stampe filter., Etc.
    """
    def __init__(self, **kwargs):
        level = kwargs.get('level')
        self._level = level
        kwargs['knot_pos'] = 'center'
        kwargs['length'] = 3
        self.sub_filter = None
        MovingWindowFilter.__init__(self, **kwargs)
        if level > 1:
            level = level-1
            kwargs['inplace']=False
            kwargs['level']=level
            self.sub_filter = StampFilter(**kwargs)

    def filteredValue(self):
        if self.sub_filter:
            return self.sub_filter.filteredValue()

        e1, e2, e3 = self._filtering_buffer[0:3]
        if not(e1 < e2 and e2 < e3) or not (e3 < e2 and e2 < e1):
            return (e1+e3)/2.0
        return e2

    def add(self, event):
        if self.sub_filter:
            sub_result =  self.sub_filter.add(event)
            if sub_result:
                self._filtering_buffer.append(sub_result[1])
                self._events.append(event)
        return MovingWindowFilter.add(self, event)

# ------

#################### TEST ###############################

if __name__ == '__main__':
    # Create a list of iohub Mouse move events.
    from collections import OrderedDict
    events=[]
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=12, type=36, device_time=139960.228, logged_time=4.668474991165567, time=4.668474991165567, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-84, y_position=157, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=13, type=36, device_time=139960.228, logged_time=4.67646576158586, time=4.67646576158586, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-85, y_position=157, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=14, type=36, device_time=139960.243, logged_time=4.684467700717505, time=4.684467700717505, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-87, y_position=158, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=15, type=36, device_time=139960.243, logged_time=4.692443981941324, time=4.692443981941324, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-88, y_position=158, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=16, type=36, device_time=139960.259, logged_time=4.700467051123269, time=4.700467051123269, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-93, y_position=157, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=17, type=36, device_time=139960.259, logged_time=4.708441823080648, time=4.708441823080648, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-96, y_position=154, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=18, type=36, device_time=139960.275, logged_time=4.716453723493032, time=4.716453723493032, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-103, y_position=150, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=19, type=36, device_time=139960.275, logged_time=4.724468038795749, time=4.724468038795749, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-117, y_position=145, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=20, type=36, device_time=139960.29, logged_time=4.73246877049678, time=4.73246877049678, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-126, y_position=138, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=21, type=36, device_time=139960.29, logged_time=4.740443542454159, time=4.740443542454159, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-135, y_position=129, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=22, type=36, device_time=139960.306, logged_time=4.748473252460826, time=4.748473252460826, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-141, y_position=123, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=23, type=36, device_time=139960.306, logged_time=4.756493303051684, time=4.756493303051684, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-145, y_position=117, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=24, type=36, device_time=139960.321, logged_time=4.764460830425378, time=4.764460830425378, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-151, y_position=113, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=25, type=36, device_time=139960.321, logged_time=4.772470014140708, time=4.772470014140708, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-153, y_position=109, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=26, type=36, device_time=139960.337, logged_time=4.780456860404229, time=4.780456860404229, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-153, y_position=109, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=27, type=36, device_time=139960.337, logged_time=4.788497135421494, time=4.788497135421494, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-153, y_position=108, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=28, type=36, device_time=139960.353, logged_time=4.796479151962558, time=4.796479151962558, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-153, y_position=103, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=29, type=36, device_time=139960.353, logged_time=4.804472035379149, time=4.804472035379149, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-150, y_position=97, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=30, type=36, device_time=139960.368, logged_time=4.81250325468136, time=4.81250325468136, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-146, y_position=91, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=31, type=36, device_time=139960.368, logged_time=4.820451161329402, time=4.820451161329402, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-142, y_position=87, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=32, type=36, device_time=139960.384, logged_time=4.828460043179803, time=4.828460043179803, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-133, y_position=78, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=33, type=36, device_time=139960.384, logged_time=4.836455341457622, time=4.836455341457622, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-124, y_position=69, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=34, type=36, device_time=139960.399, logged_time=4.844488975621061, time=4.844488975621061, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-115, y_position=63, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=35, type=36, device_time=139960.399, logged_time=4.852467369870283, time=4.852467369870283, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-104, y_position=58, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=36, type=36, device_time=139960.415, logged_time=4.860472931293771, time=4.860472931293771, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-93, y_position=54, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=37, type=36, device_time=139960.415, logged_time=4.868483020574786, time=4.868483020574786, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-84, y_position=52, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=38, type=36, device_time=139960.431, logged_time=4.8764499442477245, time=4.8764499442477245, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-78, y_position=52, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=39, type=36, device_time=139960.431, logged_time=4.8844805598200765, time=4.8844805598200765, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-73, y_position=52, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=40, type=36, device_time=139960.446, logged_time=4.892454426211771, time=4.892454426211771, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-67, y_position=53, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=41, type=36, device_time=139960.446, logged_time=4.900474174937699, time=4.900474174937699, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-64, y_position=54, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=42, type=36, device_time=139960.462, logged_time=4.908475510368589, time=4.908475510368589, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-57, y_position=58, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=43, type=36, device_time=139960.462, logged_time=4.916455112048425, time=4.916455112048425, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-53, y_position=65, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=44, type=36, device_time=139960.477, logged_time=4.924477879336337, time=4.924477879336337, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-49, y_position=73, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=45, type=36, device_time=139960.493, logged_time=4.932478611037368, time=4.932478611037368, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-47, y_position=82, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=46, type=36, device_time=139960.493, logged_time=4.940512547065737, time=4.940512547065737, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-47, y_position=90, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=47, type=36, device_time=139960.509, logged_time=4.94846588713699, time=4.94846588713699, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-47, y_position=101, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=48, type=36, device_time=139960.509, logged_time=4.956459676119266, time=4.956459676119266, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-48, y_position=112, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=49, type=36, device_time=139960.524, logged_time=4.964475198852597, time=4.964475198852597, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-50, y_position=123, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=50, type=36, device_time=139960.524, logged_time=4.972453894966748, time=4.972453894966748, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-55, y_position=132, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=51, type=36, device_time=139960.54, logged_time=4.980477869685274, time=4.980477869685274, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-57, y_position=140, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=52, type=36, device_time=139960.54, logged_time=4.9884749790944625, time=4.9884749790944625, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-61, y_position=146, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=53, type=36, device_time=139960.555, logged_time=4.997502026119037, time=4.997502026119037, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-65, y_position=153, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=54, type=36, device_time=139960.555, logged_time=5.004507533827564, time=5.004507533827564, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-69, y_position=156, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=55, type=36, device_time=139960.571, logged_time=5.012471137044486, time=5.012471137044486, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-69, y_position=157, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=56, type=36, device_time=139960.571, logged_time=5.02049752662424, time=5.02049752662424, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-70, y_position=157, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=57, type=36, device_time=139960.587, logged_time=5.028478637599619, time=5.028478637599619, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-73, y_position=158, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=58, type=36, device_time=139960.587, logged_time=5.036483293457422, time=5.036483293457422, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-76, y_position=158, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=59, type=36, device_time=139960.602, logged_time=5.044499118026579, time=5.044499118026579, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-80, y_position=156, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=60, type=36, device_time=139960.602, logged_time=5.052488681016257, time=5.052488681016257, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-88, y_position=149, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=61, type=36, device_time=139960.618, logged_time=5.060469188261777, time=5.060469188261777, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-95, y_position=143, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=62, type=36, device_time=139960.618, logged_time=5.068480786838336, time=5.068480786838336, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-99, y_position=132, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=63, type=36, device_time=139960.633, logged_time=5.07647849994828, time=5.07647849994828, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-102, y_position=114, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=64, type=36, device_time=139960.633, logged_time=5.084472590795485, time=5.084472590795485, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-100, y_position=91, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=65, type=36, device_time=139960.649, logged_time=5.092484189372044, time=5.092484189372044, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-97, y_position=72, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=66, type=36, device_time=139960.649, logged_time=5.1004631873220205, time=5.1004631873220205, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-87, y_position=46, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=67, type=36, device_time=139960.665, logged_time=5.108479615621036, time=5.108479615621036, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-75, y_position=25, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=68, type=36, device_time=139960.665, logged_time=5.116496345784981, time=5.116496345784981, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-59, y_position=2, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=69, type=36, device_time=139960.68, logged_time=5.124480173457414, time=5.124480173457414, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-49, y_position=-10, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=70, type=36, device_time=139960.68, logged_time=5.132490866468288, time=5.132490866468288, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-40, y_position=-17, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=71, type=36, device_time=139960.696, logged_time=5.140464430995053, time=5.140464430995053, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-34, y_position=-23, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=72, type=36, device_time=139960.696, logged_time=5.148476935137296, time=5.148476935137296, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-26, y_position=-25, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=73, type=36, device_time=139960.711, logged_time=5.156460762809729, time=5.156460762809729, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-17, y_position=-27, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=74, type=36, device_time=139960.711, logged_time=5.164469040959375, time=5.164469040959375, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-3, y_position=-26, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=75, type=36, device_time=139960.727, logged_time=5.172525616275379, time=5.172525616275379, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=10, y_position=-24, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=76, type=36, device_time=139960.727, logged_time=5.180502199393231, time=5.180502199393231, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=22, y_position=-19, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=77, type=36, device_time=139960.743, logged_time=5.188485725229839, time=5.188485725229839, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=31, y_position=-10, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=78, type=36, device_time=139960.743, logged_time=5.19647377889487, time=5.19647377889487, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=40, y_position=-3, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=79, type=36, device_time=139960.758, logged_time=5.20449745177757, time=5.20449745177757, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=46, y_position=8, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=80, type=36, device_time=139960.758, logged_time=5.212564893969102, time=5.212564893969102, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=51, y_position=19, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=81, type=36, device_time=139960.774, logged_time=5.22048744460335, time=5.22048744460335, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=53, y_position=30, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=82, type=36, device_time=139960.774, logged_time=5.228505080303876, time=5.228505080303876, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=53, y_position=41, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=83, type=36, device_time=139960.789, logged_time=5.236476531834342, time=5.236476531834342, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=52, y_position=52, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=84, type=36, device_time=139960.805, logged_time=5.244548803777434, time=5.244548803777434, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=45, y_position=67, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=85, type=36, device_time=139960.805, logged_time=5.252519349713111, time=5.252519349713111, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=40, y_position=76, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=86, type=36, device_time=139960.821, logged_time=5.260487480816664, time=5.260487480816664, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=36, y_position=85, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=87, type=36, device_time=139960.821, logged_time=5.26849726823275, time=5.26849726823275, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=32, y_position=91, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=88, type=36, device_time=139960.836, logged_time=5.27647656807676, time=5.27647656807676, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=28, y_position=94, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=89, type=36, device_time=139960.836, logged_time=5.284469451493351, time=5.284469451493351, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=25, y_position=96, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=90, type=36, device_time=139960.852, logged_time=5.292507009784458, time=5.292507009784458, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=19, y_position=96, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=91, type=36, device_time=139960.852, logged_time=5.300493554183049, time=5.300493554183049, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=14, y_position=96, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=92, type=36, device_time=139960.867, logged_time=5.308489758026553, time=5.308489758026553, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=8, y_position=95, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=93, type=36, device_time=139960.867, logged_time=5.316499545471743, time=5.316499545471743, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-1, y_position=91, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=94, type=36, device_time=139960.883, logged_time=5.324469487706665, time=5.324469487706665, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-7, y_position=87, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=95, type=36, device_time=139960.883, logged_time=5.332472936133854, time=5.332472936133854, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-14, y_position=80, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=96, type=36, device_time=139960.899, logged_time=5.340496307122521, time=5.340496307122521, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-18, y_position=74, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=97, type=36, device_time=139960.899, logged_time=5.348478927393444, time=5.348478927393444, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-22, y_position=68, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=98, type=36, device_time=139960.914, logged_time=5.356487809243845, time=5.356487809243845, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-24, y_position=60, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=99, type=36, device_time=139960.914, logged_time=5.3645060486742295, time=5.3645060486742295, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-24, y_position=56, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=100, type=36, device_time=139960.93, logged_time=5.3725043655140325, time=5.3725043655140325, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-24, y_position=53, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=101, type=36, device_time=139960.93, logged_time=5.380504493514309, time=5.380504493514309, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-24, y_position=50, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=102, type=36, device_time=139960.945, logged_time=5.388510054937797, time=5.388510054937797, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-23, y_position=47, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=103, type=36, device_time=139960.945, logged_time=5.396494788175914, time=5.396494788175914, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-19, y_position=41, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=104, type=36, device_time=139960.961, logged_time=5.404487973457435, time=5.404487973457435, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-13, y_position=37, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=105, type=36, device_time=139960.961, logged_time=5.412510740745347, time=5.412510740745347, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-4, y_position=32, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=106, type=36, device_time=139960.977, logged_time=5.420487323863199, time=5.420487323863199, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=4, y_position=30, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=107, type=36, device_time=139960.977, logged_time=5.4285116004466545, time=5.4285116004466545, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=15, y_position=30, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=108, type=36, device_time=139960.992, logged_time=5.436502069002017, time=5.436502069002017, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=26, y_position=32, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=109, type=36, device_time=139960.992, logged_time=5.4445049136993475, time=5.4445049136993475, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=37, y_position=36, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=110, type=36, device_time=139961.008, logged_time=5.452508362126537, time=5.452508362126537, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=43, y_position=38, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=111, type=36, device_time=139961.008, logged_time=5.4604792099271435, time=5.4604792099271435, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=49, y_position=42, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=112, type=36, device_time=139961.023, logged_time=5.468485676916316, time=5.468485676916316, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=53, y_position=46, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=113, type=36, device_time=139961.023, logged_time=5.476476145471679, time=5.476476145471679, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=53, y_position=49, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=114, type=36, device_time=139961.039, logged_time=5.484498309058836, time=5.484498309058836, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=52, y_position=54, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=115, type=36, device_time=139961.039, logged_time=5.492511718766764, time=5.492511718766764, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=50, y_position=60, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=116, type=36, device_time=139961.055, logged_time=5.500507318880409, time=5.500507318880409, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=44, y_position=69, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=117, type=36, device_time=139961.055, logged_time=5.508503522723913, time=5.508503522723913, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=40, y_position=73, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=118, type=36, device_time=139961.07, logged_time=5.516478294681292, time=5.516478294681292, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=36, y_position=79, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=119, type=36, device_time=139961.07, logged_time=5.524498647137079, time=5.524498647137079, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=33, y_position=81, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=120, type=36, device_time=139961.086, logged_time=5.532514773571165, time=5.532514773571165, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=29, y_position=82, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=121, type=36, device_time=139961.086, logged_time=5.5405037328309845, time=5.5405037328309845, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=24, y_position=82, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=122, type=36, device_time=139961.101, logged_time=5.548520764830755, time=5.548520764830755, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=18, y_position=81, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=123, type=36, device_time=139961.117, logged_time=5.556483160646167, time=5.556483160646167, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=9, y_position=79, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=124, type=36, device_time=139961.117, logged_time=5.564633311791113, time=5.564633311791113, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-6, y_position=72, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=125, type=36, device_time=139961.133, logged_time=5.572515413514338, time=5.572515413514338, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-15, y_position=63, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=126, type=36, device_time=139961.133, logged_time=5.580504372774158, time=5.580504372774158, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-24, y_position=54, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=127, type=36, device_time=139961.148, logged_time=5.588501180318417, time=5.588501180318417, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-28, y_position=42, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=128, type=36, device_time=139961.148, logged_time=5.596497686026851, time=5.596497686026851, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-33, y_position=31, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=129, type=36, device_time=139961.164, logged_time=5.604483324859757, time=5.604483324859757, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-33, y_position=23, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=130, type=36, device_time=139961.164, logged_time=5.612715279363329, time=5.612715279363329, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-33, y_position=17, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=131, type=36, device_time=139961.179, logged_time=5.620532481727423, time=5.620532481727423, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-32, y_position=12, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=132, type=36, device_time=139961.179, logged_time=5.6285226484178565, time=5.6285226484178565, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-30, y_position=6, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=133, type=36, device_time=139961.195, logged_time=5.636515531834448, time=5.636515531834448, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-28, y_position=2, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=134, type=36, device_time=139961.195, logged_time=5.644488794496283, time=5.644488794496283, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-24, y_position=-4, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=135, type=36, device_time=139961.211, logged_time=5.652492544788402, time=5.652492544788402, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-15, y_position=-8, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=136, type=36, device_time=139961.211, logged_time=5.660516519506928, time=5.660516519506928, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=-7, y_position=-13, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=137, type=36, device_time=139961.226, logged_time=5.668525703222258, time=5.668525703222258, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=7, y_position=-13, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    events.append(OrderedDict(experiment_id=0, session_id=0, device_id=0, event_id=138, type=36, device_time=139961.226, logged_time=5.676524020062061, time=5.676524020062061, confidence_interval=0.0, delay=0.0, filter_id=0, display_id=0, button_state=0, button_id=0, pressed_buttons=0, x_position=18, y_position=-11, scroll_dx=0, scroll_x=0, scroll_dy=0, scroll_y=0, modifiers=[], window_id=984208))
    #events = [e.values() for e in events]

    # Using event class and fields
    #mx_filter = MedianFilter(5, EventConstants.MOUSE_MOVE, 'x_position', knot_pos='center', inplace = True)
    #my_filter = MedianFilter(5, EventConstants.MOUSE_MOVE, 'y_position', knot_pos='center', inplace = True)
#    mx_filter = WeightedAverageFilter([17.0,33.0,50.0,33.0,17.0], EventConstants.MOUSE_MOVE, 'x_position', knot_pos='center', inplace = True)
#    my_filter = WeightedAverageFilter([17.0,33.0,50.0,33.0,17.0], EventConstants.MOUSE_MOVE, 'y_position', knot_pos='center', inplace = True)
    #mx_filter = StampFilter(EventConstants.MOUSE_MOVE, 'x_position', level = 2, inplace = True)
    #my_filter = StampFilter(EventConstants.MOUSE_MOVE, 'y_position', level = 2, inplace = True)

    #print "FIRST SOURCE EVENT ID:",events[0]['event_id']
    #for e in events:
    #    r = mx_filter.add(e)
    #    if r:
    #        event, filtered_x=r

    #    r = my_filter.add(e)
    #    if r:
    #        event, filtered_y=r
    #    if r:
    #        print "filtered event: ",event['event_id'],filtered_x, filtered_y

    # Using values only
    mx_filter = WeightedAverageFilter(weights=[17.0,33.0,50.0,33.0,17.0], event_type=None, event_field_name=None, knot_pos='center', inplace = True)
    my_filter = WeightedAverageFilter(weights=[17.0,33.0,50.0,33.0,17.0], event_type=None, event_field_name=None, knot_pos='center', inplace = True)


    print "FIRST SOURCE EVENT ID:",events[0]['event_id']
    for e in events:
        r = mx_filter.add(e['x_position'])
        filtered_x=None
        filtered_y=None
        if r:
            _, filtered_x=r

        r = my_filter.add(e['y_position'])
        if r:
            _, filtered_y=r

        print "filtered values: ", filtered_x, filtered_y