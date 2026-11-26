"""Calls through attributes: self.x.m(), where the class of x is set in another method."""


class Engine:
    def start(self):
        return "started"


class TurboEngine(Engine):
    def boost(self):
        return "boost"


class Radio:
    def play(self):
        return "music"


class Battery:
    def charge(self):
        return "charged"


class Logger:
    def write(self, text):
        return text


def make_logger():
    return Logger()


class Car:
    def __init__(self, battery: Battery):
        self.engine = Engine()          # from a constructor
        self.battery = battery          # from a typed parameter
        self.radio = None               # None says nothing
        self.log = make_logger()        # a value we cannot tell
        self.part = Engine()            # set to two different classes below
        spare = Radio()
        self.spare = spare              # from a local variable of a known class
        self.gauge: Battery = battery   # from an annotation

    def install_radio(self, radio: Radio):
        self.radio = radio

    def swap_part(self):
        self.part = Radio()

    def drive(self):
        self.engine.start()
        self.battery.charge()
        self.radio.play()
        self.log.write("go")
        self.part.start()
        self.spare.play()
        self.gauge.charge()

    def use_part(self):
        self.part.start()               # Engine in one method, Radio in another: not linked

    def use_log(self):
        self.log.write("x")             # unknown class: not linked

    def deep(self):
        self.engine.owner.start()       # two levels: not linked


class SportsCar(Car):
    def race(self):
        self.engine.start()             # attribute set in the parent class
        self.missing.start()            # attribute nobody sets: not linked


class Garage:
    def __init__(self):
        self.engine = TurboEngine()

    def service(self):
        self.engine.start()             # method found on the attribute class's parent
        self.engine.boost()
