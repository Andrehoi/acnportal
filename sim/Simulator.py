
class Simulator:
    '''
    The Simulator class is the central class of the ACN research portal simulator.
    '''

    def __init__(self, tc, max_iterations=1000):
        self.iteration = 0
        self.last_schedule_update = -1
        self.test_case = tc
        self.scheduler = None
        self.schedules = {}
        self.max_iterations = max_iterations

    def define_scheduler(self, scheduler):
        '''
        Sets the scheduler class of the simulator.

        :param scheduler: The scheduling algorithm that should be used by the simulator. This object must extend BaseAlgorithm.
        :return: None
        '''
        self.scheduler = scheduler

    def run(self):
        '''
        The most essential function of the Simulator class. Runs the main function of
        the simulation from start to finish and calls for the scheduler when needed.

        :return: None
        '''
        schedule_horizon = 0
        while self.iteration < self.max_iterations:
            if self.iteration >= self.last_schedule_update + schedule_horizon:
                # call the scheduling algorithm
                self.scheduler.run()
                self.last_schedule_update = self.iteration
                schedule_horizon = self.get_schedule_horizon()
            pilot_signals = self.get_current_pilot_signals()
            self.test_case.step(pilot_signals, self.iteration)
            self.iteration = self.iteration + 1


    def get_current_pilot_signals(self):
        '''
        Function for extracting the pilot signals at the current time for the active EVs

        :return: (dict) A dictionary where key is the EV id and the value is a number with the charging rate
        '''
        pilot_signals = {}
        for ev_id, sch_list in self.schedules.items():
            iterations_since_last_update = self.iteration - self.last_schedule_update
            if iterations_since_last_update > len(sch_list):
                pilot = sch_list[-1]
            else:
                pilot = sch_list[iterations_since_last_update]
            pilot_signals[ev_id] = pilot
        return pilot_signals

    def get_schedule_horizon(self):
        min_horizon = 0
        for ev_id, sch_list in self.schedules.items():
            if min_horizon > len(sch_list):
                min_horizon = len(sch_list)
        return min_horizon

    def update_schedules(self, new_schedule):
        '''
        Update the schedules used in the simulation.
        This function is called by the interface to the scheduling algorithm.

        :param new_schedule: (dict) Dictionary where key is the id of the EV and value is a list of scheduled charging rates.
        :return:
        '''
        self.schedules = new_schedule

    def get_active_EVs(self):
        '''
        Returns the current active EVs connected to the system.

        :return:  (list) List of EVs currently plugged in and not finished charging
        '''
        return self.test_case.get_active_EVs(self.iteration)

    def get_simulation_data(self):
        '''
        Returns the data from the simulation.
        :return: (dict) Dictionary where key is the id of the EV and value is a list of dicts representing every sample.
        '''
        return self.test_case.get_charging_data()



