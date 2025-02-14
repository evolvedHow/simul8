from pickle import NONE

from typing_extensions import dataclass_transform
from collections import defaultdict
import simpy
import random
import yaml
import time
import json
import csv
import pandas as pd


class Simul8():
  """
  A class for simulating processes and resource management.

  This class provides functionality to define tasks, resources, workflows,
  and triggers for simulating various scenarios. It utilizes the `simpy`
  library for discrete event simulation.
  """

  DEFAULT_LOG = 'logs\default.csv'
  
  def __init__(self, **kwargs):
    """
    Initialize the Simul8 simulation environment.

    Args:
      profile (dict): A dictionary containing the simulation profile settings.
    """
    self.config = {}
    self.utilization = {}
    self.tasks = {}
    self.taskbox = {}
    self.resources = {}
    self.metrics = {}
    self.taskState = {}

    self.run_name: str = kwargs.get('run_name', '**Default**')
    self.iterations = kwargs['profile'].get('iterations',1)


    self.config['profile'] = kwargs['profile']
    self.useAcqTime =  self.config['profile'].get('use_acquire_time',False)
    self.useRlsTime =  self.config['profile'].get('use_release_time',False)

    self.config['resources'] = kwargs['resources']
    self.config['tasks'] = kwargs['tasks']
    self.config['flow'] = kwargs['flow']
    self.config['triggers'] = kwargs['triggers']
    self.config['resource_clones'] = kwargs.get('resource_clones',{})
    self.config['output'] = kwargs.get('output',None)
    self.config['trace'] = kwargs.get*('trace',None)

    # Now expand the resources to also include clones
    if (self.config['resource_clones']):
      for parent in self.config['resource_clones']:
        if parent in self.config['resources']:
          for cln in self.config['resource_clones'][parent]:
            if cln not in self.config['resources']:
              self.config['resources'][cln] = self.config['resources'][parent].copy()



    self.inbox: dict = {}
    self.utilization: dict = {}
    self.log: list = []
    self.trace: list = []
    self.log.append('ID,RUN_NO,MESSAGE,TASK/RESOURCE,START,DURATION,VARIANCE,RESOURCE')
    self.log_id: int = 0

    self.env = None

  # define the resource template used to track resources
    self.resMetrics: list = ['task_count',
                             'task_duration',
                             'break_count',
                             'break_duration',
                             'current_sprint']

 #____________________________________________________________________
  def run(self, **kwargs) -> pd.DataFrame:

    # initialize all simpy values
    self.env = simpy.Environment()
    self._defineResources()
    simpy.Process(self.env, self._eventInjector())


    print('about to start')
    print('Seeded iterations; about to start')
    self.env.run()
    print('done')

    if self.config['output']:
      with open(self.config['output'], "w") as l:
        l.write(str(self.log))

    return(self.log)
  #____________________________________________________________________
  # Private functions here
  #____________________________________________________________________


  def _eventInjector(self):
    '''
    For each iteration, initialize all the task states
    and loop thru all the trigger tasks and inject them
    into the orchstrator
    '''

    iter = 0
    for _ in range(self.iterations):
      iter += 1
      for t in self.config['tasks']:
        self.taskState[f'{t}{iter}'] = simpy.resources.store.Store(self.env,capacity=1)

      for t in self.config['triggers']:
        yield simpy.Process(self.env,self._taskOrchstrator(t, iter))
  #____________________________________________________________________
  # Can be invoked for
  def _taskOrchstrator(self, task, iteration):
    '''
    For the given task/iteration, determine which handoff to use
    if it exists, and then call the task with its iteration# and handoffr choice
    '''
    handoff_choice = []
    handoff_count = 0
    handoff_choice: list = self._getHandoff(task)
    print(f'Handoff choice is {handoff_choice}')
    yield simpy.Process(self.env, self._performTask(task, iteration, handoff_choice))


  #____________________________________________________________________
  def _getHandoff(self,task) -> list:
    '''
    Determines the handoff choices (if any) for a given task,
    and returns them as a list
    '''
    handoff_choice = []
    if 'handoffs' in self.config['flow'].get(task, {}):
      handoff_length = len(self.config['flow'][task]['handoffs'])
      if handoff_length:
        if handoff_length == 1:
          handoff_choice = list(self.config['flow'][task]['handoffs'])[0]
        else:
          handoff_choice = random.choice(list(self.config['flow'][task]['handoffs']))
    print(f'Handoff returning with {handoff_choice}')
    return(handoff_choice)
  #____________________________________________________________________


  def _performTask(self, task, iteration, handoff_choice):

    if task in self.config['flow']:
      flowTask = True
    else:
      flowTask = False

    targetDuration: float = 0.00
    in_time: float = self.env.now
    out_time: float = 0.00
    variance: float = 0.00
    # acquire the resources needed for the task
    print(f'Acquiring resources for {task}')
    acquiredResources = yield from self._acquireResources(task, iteration)

    # calculate the target duration to use
    if 'duration' in self.config['tasks'][task]:
      durMin = self.config['tasks'][task]['duration'][0]
      durMax = self.config['tasks'][task]['duration'][1]
    else:
      durMin = 1
      durMax = 1

    targetDuration = random.uniform(durMin,durMax)

    # perform the task, including calling any plugins

    yield(self.env.timeout(targetDuration))

    plugin = None
    parameter = None

    if 'plugin' in self.config['tasks'][task]:
      plugin = self.config['tasks'][task].get('plugin', None)
      parameter = self.config['tasks'][task].get('parameter', None)
      if plugin:
        self._invoke_plugin(task=task,
                            iteration = iteration,
                            plugin=plugin,
                            parameter=parameter)
    out_time = self.env.now
    actualDuration = out_time - in_time
    variance = abs(targetDuration - actualDuration)
    #if variance < 1e-10:
    #  variance = 0.00

    # release resources needed by task, and log the work
    if acquiredResources:
      yield from self._releaseResources(task, targetDuration, iteration)
    if handoff_choice:
      task_name = f'{handoff_choice} :: {task}'
    else:
      task_name = task

    self._log(iteration=iteration,
              msg='Performed task',
              task_name=task_name,
              plugin=plugin,
              parameter=parameter,
              start=in_time,
              duration=actualDuration,
              variance=variance)

    print(f'{task}- duration={targetDuration}, in={in_time}, out={out_time}, variance={variance}')
    # mark task state as complete
    self.taskState[f'{task}{iteration}'].put(1)

    # if this task needs to hand off to others, let them know

    if handoff_choice:
      for tsk in self.config['flow'][task]['handoffs'][handoff_choice]:
        yield simpy.Process(self.env, self._taskOrchstrator(tsk, iteration))
    else:
      print(f'No handoff for {task}')

    return

  #____________________________________________________________________

  def _invoke_plugin(self, task, iteration, plugin, parameter):
      result = None
      plugin_function = globals().get(plugin)
      if callable(plugin_function):
        result = plugin_function(task=task,
                                 iteration=iteration,
                                 parameter=parameter)
      else:
        print(f'could not call plugin {plugin}')
      return
  #____________________________________________________________________

  def _defineTasks(self, **kwargs) -> bool:

    results: bool = False
    if 'tasks' in self.config:
      results = True
      for t in self.config['tasks']:
        self.tasks[t] = self.env.process(self._executeTask(task=t))
        self.taskbox[t] = simpy.resources.resource.Resource(self.env,capacity=10)

    return(results)
  #____________________________________________________________________

  def _defineResources(self, **kwargs) -> bool:

    results: bool = False
    for t in self.config['tasks']:
      if 'resources' in self.config['tasks'][t]:
        for tr in self.config['tasks'][t]['resources']:
          if tr not in self.resources:
            self.resources[tr] = simpy.resources.store.Store(
                self.env,
                capacity=self.config['resources'][tr]['capacity'])
            self.metrics[tr] = {metric:0 for metric in self.resMetrics}

    return(results)
  #___________________________________________________________________

  def _acquireResources(self,task, iter) -> list:
    requests: list = []
    acquire_time = 0.0
    time_in = self.env.now

    if 'resources' in self.config['tasks'][task]:
      for rsc in self.config['tasks'][task]['resources']:
        req = self.resources[rsc].get()
        requests.append(req)
        if self.useAcqTime:
          if 'acquire_time' in self.config['resources'][rsc]:
            acquire_time += self.config['resources'][rsc]['acquire_time']

      print(f'Acquiring resources for {iter}/{task} with acquire time of {acquire_time}')
      yield simpy.AllOf(self.env, [requests and self.env.timeout(acquire_time)])
      time_out = self.env.now

      self._log(msg='Acquired resources',
                task_name=f'{self.config["tasks"][task]["resources"]}',
                start=time_in,
                iteration=iter,
                duration=(time_out - time_in))
      return requests
    else:
      return None

  #____________________________________________________________________

  def _releaseResources(self,task, dur, iter):
    release_time = 0.0
    released_resources = []
    if 'resources' in self.config['tasks'][task]:
      for rsc in self.config['tasks'][task]['resources']:
        if self.useRlsTime:
          if 'release_time' in self.config['resources'][rsc]:
            yield self.env.timeout(self.config['resources'][rsc]['release_time'])
        # update resources utilization
        self.metrics[rsc]['task_count'] += 1
        self.metrics[rsc]['task_duration'] += dur
        self.metrics[rsc]['current_sprint'] += 1
        if 'break_after' in self.config['resources'][rsc]:
          break_time = self.config['resources'][rsc]['break_after']
          print(f'Evaluating break for {rsc}. break after {break_time} and resource is at {self.metrics[rsc]}')
          if self.metrics[rsc]['current_sprint'] >= break_time:
            yield simpy.Process(self.env, self._takeBreak(rsc, self.metrics[rsc], dur))
          else:
            self.resources[rsc].put(1)
            released_resources.append(rsc)

        else:
          self.resources[rsc].put(1)
          released_resources.append(rsc)


        if released_resources:
          self._log(msg='Released resources',
                    iteration=iter,
                    task_name=f'{self.config["tasks"][task]["resources"]}')
        else:
          print(f'Did not release anything for {task}')
    return
  #____________________________________________________________________
  def _takeBreak(self,res, metrics, dur):
    yield self.env.timeout(dur)
    metrics['break_count'] += 1
    metrics['break_duration'] += dur
    metrics['current_sprint'] = 0
    self.resources[res].put(metrics)
    return
  #____________________________________________________________________
  def insights(self, **kwargs):
    results = []
    for rsc in self.metrics:
      txt = f'task count = {self.metrics[rsc]["task_count"]}'
      txt += f', duration = {self.metrics[rsc]["task_duration"]}'
      txt += f', break count = {self.metrics[rsc]["break_count"]}'
      txt += f', break duration = {self.metrics[rsc]["break_duration"]}'
      results.append(f'0,0,Metrics,,,0,0,0,{rsc},{txt}')

    self._log(msg='Resource break/offline',
              task_name=f'{results}')
    return results
  #____________________________________________________________________
  def __str__(self):
    return "\n".join(self.log)
  #____________________________________________________________________

  def _log(self, **kwargs):
    self.log_id += 1
    msg = kwargs.get('msg','')
    task_name = kwargs.get('task_name','')
    iteration = kwargs.get('iteration',0)
    start = kwargs.get('start',0)
    duration = kwargs.get('duration',0)
    variance = kwargs.get('variance',0)
    resource = kwargs.get('resource','')
    plugin = kwargs.get('plugin','')
    parameter = kwargs.get('parameter','')

    if plugin:
      resource = f'Plugin={plugin}({parameter})'




    logEntry = f'{self.log_id},{iteration},{msg},{task_name},{start:.2f},{duration:.2f},{variance},{resource}'
    self.log.append(logEntry)
    return
  #____________________________________________________________________
