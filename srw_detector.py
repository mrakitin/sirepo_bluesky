import datetime
from pathlib import Path

from bluesky.tests.utils import _print_redirect

from ophyd import Device, Signal, Component as Cpt
from ophyd.sim import SynAxis, NullStatus, new_uid

from srw_handler import read_srw_file
from sirepo_bluesky import SirepoBluesky

class SRWDetector(Device):
    """
    Use SRW code based on the value of the motor.

    Parameters
    ----------
    name : str
        The name of the detector
    optic_name : str
        The name of the optic being accessed by Bluesky
    param0 : str
        The name of the first parameter of the optic being changed
    motor0 : Ophyd Component
        The first Ophyd component being controlled in Bluesky scan
    field0 : str
        The name corresponding to motor0 that is shown as axis in Bluesky scan
    motor1 :
        The second Ophyd component being controlled in Bluesky scan
    field1 : str
        The name corresponding to motor1 that is shown as axis in Bluesky scan
    param1 : str
        The name of the second parameter of the optic being changed
    reg : Databroker register
    sim_id : str
        The simulation id corresponding to the Sirepo simulation being run on
        local server
    watch_name : str
        The name of the watchpoint viewing the simulation
    sirepo_server : str
        Address that identifies access to local Sirepo server

    """
    image = Cpt(Signal)
    shape = Cpt(Signal)
    mean = Cpt(Signal)
    photon_energy = Cpt(Signal)
    horizontal_extent = Cpt(Signal)
    vertical_extent = Cpt(Signal)

    def __init__(self, name, optic_name, param0, motor0, field0, motor1=None, field1=None, param1=None, reg=None,
                 sim_id=None, watch_name=None, sirepo_server='http://10.10.10.10:8000',
                 **kwargs):
        super().__init__(name=name, **kwargs)
        self.reg = reg
        self.optic_name = optic_name
        self.param0 = param0
        self.param1 = param1
        self._motor0 = motor0
        self._motor1 = motor1
        self._field0 = field0
        self._field1 = field1
        self._resource_id = None
        self._result = {}
        self._sim_id = sim_id
        self.watch_name = watch_name
        self._sirepo_server = sirepo_server
        self._hints = None
        assert sim_id, 'Simulation ID must be provided. Currently it is set to {}'.format(sim_id)

    @property
    def hints(self):
        if self._hints is None:
            return {'fields': [self.mean.name]}
        return self._hints

    @hints.setter
    def hints(self, val):
        self._hints = dict(val)

    def trigger(self):
        super().trigger()
        x = self._motor0.read()[self._field0]['value']
        y = self._motor1.read()[self._field1]['value']
        datum_id = new_uid()
        date = datetime.datetime.now()
        srw_file = Path('/tmp/data') / Path(date.strftime('%Y/%m/%d')) / \
            Path('{}.dat'.format(datum_id))

        sim_id = self._sim_id
        sb = SirepoBluesky(self._sirepo_server)
        data = sb.auth('srw', sim_id)

        #Get units we need to convert to
        sb_data = sb.get_datafile().decode("utf-8")[200:300]
        start = sb_data.find('[')
        end = sb_data.find(']')
        final_units = sb_data[start + 1:end]

        element = sb.find_element(data['models']['beamline'], 'title', self.optic_name)
        element[self.param0] = x * 1000
        element[self.param1] = y * 1000
        watch = sb.find_element(data['models']['beamline'], 'title', self.watch_name)
        data['report'] = 'watchpointReport{}'.format(watch['id'])
        sb.run_simulation()
        
        with open(srw_file, 'wb') as f:
            f.write(sb.get_datafile())
        ret = read_srw_file(srw_file)
        self.image.put(datum_id)
        self.shape.put(ret['shape'])
        self.mean.put(ret['mean'])
        self.photon_energy.put(ret['photon_energy'])
        self.horizontal_extent.put(ret['horizontal_extent'])
        self.vertical_extent.put(ret['vertical_extent'])

        self._resource_id = self.reg.insert_resource('srw', srw_file, {})
        self.reg.insert_datum(self._resource_id, datum_id, {})

        return NullStatus()

    def describe(self):
        res = super().describe()
        res[self.image.name].update(dict(external="FILESTORE"))
        return res

    def unstage(self):
        super().unstage()
        self._resource_id = None
        self._result.clear()


class Component(Device):
    x = Cpt(SynAxis, delay=0.01)
    y = Cpt(SynAxis, delay=0.02)

def get_dict_parameters(d):
    non_parameters = ['title', 'shape', 'type', 'id']
    parameters = []
    for key in d:
        if key not in non_parameters:
            parameters.append(key)
            print(f'PARAMETERS:        {parameters} \n')

def get_options():
    sb = SirepoBluesky('http://10.10.10.10:8000')
    data = sb.auth('srw', sim_id)
    watchpoints = {}
    print("Tunable parameters for Bluesky scan: ")
    for i in range(0, len(data['models']['beamline'])):
        print('OPTICAL ELEMENT:    ' + data['models']['beamline'][i]['title'])
        get_dict_parameters(data['models']['beamline'][i])
        if data['models']['beamline'][i]['type'] == 'watch':
            watchpoints[data['models']['beamline'][i]['title']] = \
            str(data['models']['beamline'][i]['position'])
    print(f'WATCHPOINTS:       {watchpoints}')
    if len(watchpoints) < 1:
        raise ValueError('No watchpoints found. This simulation will not work')

sim_id = input("Please enter sim ID: ")
get_options()
optic_id = input("Please select optical element: ")
param0 = input("Please select parameter: ")
param1 = input("Please select another parameter or press ENTER to only use one: ")
watch_name = input("Please select watchpoint: ")

c = Component(name=optic_id)
srw_det = SRWDetector(name='srw_det', optic_name=optic_id, param0=param0,
                      param1=param1, motor0=c.x, field0=optic_id + '_x',
                      motor1=c.y, field1=optic_id + '_y', reg=db.reg,
                      sim_id=sim_id, watch_name=watch_name)
srw_det.read_attrs = ['image', 'mean', 'photon_energy']
srw_det.configuration_attrs = ['horizontal_extent', 'vertical_extent', 'shape']
