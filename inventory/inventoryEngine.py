def inventoryEngine(**kwargs):
  task = kwargs.get('task', None)
  iteration = kwargs.get('iteration', None)
  parameter = kwargs.get('parameter', None)

  if parameter == 'reserve':
    print(f'Reserving inventory for {task}/{iteration}')
  elif parameter == 'fulfill':
    print(f'Releasing inventory for {task}/{iteration}')
  else:
    print(f'Unknown parameter {parameter} for {task}/{iteration}')
  return
