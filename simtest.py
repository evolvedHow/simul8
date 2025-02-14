import simul8

def main():
  SIM_LOG = '/content/drive/MyDrive/1data/curbside2503.csv'
  TRACE_LOG = '/content/drive/MyDrive/1data/curbside2503_trace.txt'
  CFG_FILE = '/content/drive/MyDrive/1data/curbside2503.yaml'

  with open(CFG_FILE) as f:
    config_file = yaml.safe_load(f)
    sim = Simul8(run_name='Orders',
                 profile=config_file['profile'],
                 tasks=config_file['tasks'],
                 resources=config_file['resources'],
                 resource_clones=config_file['resource_clones'],
                 flow=config_file['flow'],
                 triggers=config_file['triggers'],
                 output=SIM_LOG,
                 trace=TRACE_LOG)

    print('calling sim')
    sim.run()
    print(f'______________ [ OUTPUT ] ___________________')
    with open(SIM_LOG, "w") as l:
      l.write(str(sim))



    print(f'______________ [ INSIGHTS ] ___________________')
    ins = sim.insights()
    print(ins)
    print(*ins,sep='\n')
  return
  
    

if __name__ == '__main__':
  main()