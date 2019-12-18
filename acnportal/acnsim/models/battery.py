import numpy as np
from scipy.special import lambertw

IDEAL = 'Ideal'
NOISY = 'Noisy'
TWO_STAGE = 'TwoStage'


class Battery:
    """This class models the behavior of a battery and battery management system (BMS).

    Args:
        capacity (float): Capacity of the battery [kWh]
        init_charge (float): Initial charge of the battery [kWh]
        max_power (float): Maximum charging rate of the battery [kW]
    """

    def __init__(self, capacity, init_charge, max_power):
        if init_charge > capacity:
            raise ValueError('Initial Charge cannot be greater than capacity.')
        self._capacity = capacity
        self._current_charge = init_charge
        self._init_charge = init_charge
        self._max_power = max_power
        self._current_charging_power = 0

    @property
    def _soc(self):
        """ Returns the state of charge of the battery as a percent."""
        return self._current_charge / self._capacity

    @property
    def max_charging_power(self):
        """ Returns the maximum charging power of the Battery."""
        return self._max_power

    @property
    def current_charging_power(self):
        """ Returns the current draw of the battery on the AC side."""
        return self._current_charging_power

    def charge(self, pilot, voltage, period):
        """ Method to "charge" the battery

        Args:
            pilot (float): Pilot signal passed to the battery. [A]
            voltage (float): AC voltage provided to the battery charger. [V]
            period (float): Length of the charging period. [minutes]

        Returns:
            float: actual charging rate of the battery. [A]

        Raises:
            ValueError: if voltage or period are <= 0.
        """
        if voltage <= 0:
            raise ValueError('Voltage must be greater than 0. Got {0}'.format(voltage))
        if period <= 0:
            raise ValueError('period must be greater than 0. Got {0}'.format(voltage))

        # Rate which would fill the battery in period minutes.
        rate_to_full = (self._capacity - self._current_charge) / (period / 60)

        charge_power = min([pilot*voltage / 1000, self._max_power, rate_to_full])
        self._current_charge += charge_power * (period / 60)
        self._current_charging_power = charge_power
        return charge_power * 1000 / voltage

    def reset(self, init_charge=None):
        """ Reset battery to initial state. If init_charge is not
        given (is None), the battery is reset to its initial charge
        on initialization.

        Args:
            init_charge (float): charge battery should be reset to. [acnsim units]

        Returns:
            None
        """
        if init_charge is None:
            self._current_charge = self._init_charge
        else:
            if init_charge > self._capacity:
                raise ValueError('Initial Charge cannot be greater than capacity.')
            self._current_charge = init_charge
        self._current_charging_power = 0


class Linear2StageBattery(Battery):
    """ Extends Battery with a simple piecewise linear model of battery dynamics based on SoC.

    Battery model based on a piecewise linear approximation of battery behavior. The battery will charge at the
    minimum of max_rate and the pilot until it reaches _transition_soc. After this, the maximum charging rate of the
    battery will decrease linearly to 0 at 100% state of charge.

    For more info on model: https://www.sciencedirect.com/science/article/pii/S0378775316317396

    All public attributes are the same as Battery.

    Args:
        noise_level (float): Standard deviation of the noise to add to the charging process. This noise in the measurement of charging power. (kW)
        transition_soc (float): State of charging when transitioning from constant current to constraint voltage.
    """

    def __init__(self, capacity, init_charge, max_power, noise_level=0, transition_soc=0.8):
        super().__init__(capacity, init_charge, max_power)
        self._noise_level = noise_level
        self._transition_soc = transition_soc

    def charge_old(self, pilot, voltage, period):
        """ Method to "charge" the battery based on a two-stage linear battery model.

        Args:
            pilot (float): Pilot signal passed to the battery. [A]
            voltage (float): AC voltage provided to the battery charger. [V]
            period (float): Length of the charging period. [minutes]

        Returns:
            float: actual charging rate of the battery.

        """
        if voltage <= 0:
            raise ValueError('Voltage must be greater than 0. Got {0}'.format(voltage))
        if period <= 0:
            raise ValueError('period must be greater than 0. Got {0}'.format(voltage))

        # Rate which would fill the battery in period minutes.
        rate_to_full = (self._capacity - self._current_charge) / (period / 60)

        if self._soc < self._transition_soc:
            charge_power = min([pilot * voltage / 1000, self._max_power, rate_to_full])
            if self._noise_level > 0:
                charge_power -= abs(np.random.normal(0, self._noise_level))
        else:
            charge_power = min([pilot * voltage / 1000,
                                (1 - self._soc) / (1 - self._transition_soc) * self._max_power,
                                rate_to_full])
            if self._noise_level > 0:
                charge_power += np.random.normal(0, self._noise_level)
                # ensure that noise does not cause the battery to violate any hard limits.
                charge_power = min([charge_power, pilot * voltage / 1000, self._max_power, rate_to_full])
        self._current_charge += charge_power * (period / 60)
        self._current_charging_power = charge_power
        return charge_power * 1000 / voltage

    def charge(self, pilot, voltage, period):
        """ Method to "charge" the battery based on a two-stage linear battery model.

        Args:
            pilot (float): Pilot signal passed to the battery. [A]
            voltage (float): AC voltage provided to the battery charger. [V]
            period (float): Length of the charging period. [minutes]

        Returns:
            float: actual charging rate of the battery.

        """
        if voltage <= 0:
            raise ValueError('Voltage must be greater than 0. Got {0}'.format(voltage))
        if period <= 0:
            raise ValueError('period must be greater than 0. Got {0}'.format(voltage))

        pilot_dsoc = pilot * voltage / 1000 / self._capacity / (60 / period)
        max_dsoc = self._max_power / self._capacity / (60 / period)

        if pilot_dsoc > max_dsoc:
            pilot_dsoc = max_dsoc

        pilot_transition_soc = self._transition_soc + (pilot_dsoc - max_dsoc) \
                               / max_dsoc * (self._transition_soc - 1)
        assert pilot_transition_soc >= self._transition_soc
        # TODO: Assumes nonnegative pilot signal. Might want to remove
        # this restriction.
        assert pilot_transition_soc <= 1

        if self._soc < pilot_transition_soc:
            if 1 <= (pilot_transition_soc - self._soc) / pilot_dsoc:
                curr_soc = pilot_dsoc + self._soc
            else:
                curr_soc = 1 + np.exp((pilot_dsoc + self._soc \
                                       - pilot_transition_soc) \
                                    / (pilot_transition_soc - 1)) \
                           * (pilot_transition_soc - 1)
        else:
            curr_soc = 1 + np.exp(pilot_dsoc \
                                  / (pilot_transition_soc - 1)) \
                       * (self._soc - 1)
        if self._noise_level > 0:
            raw_noise = np.random.normal(0, self._noise_level)
            scaled_noise = raw_noise * (period / 60) / self._capacity
            curr_soc -= abs(scaled_noise)
        dsoc = curr_soc - self._soc
        self._current_charge = curr_soc * self._capacity
        # Average charging power over this period
        self._current_charging_power = dsoc * self._capacity / (period / 60)
        return self._current_charging_power * 1000 / voltage


def batt_cap_fn_old(requested_energy, stay_dur, voltage, period):
    def _get_init_cap(requested_energy, stay_dur, cap, voltage, period, max_rate=32):
        batt = Linear2StageBattery(cap, 0, max_rate, noise_level=0)
        actual_rates = []
        while True:
            actual_rates.append(batt.charge(max_rate, voltage, period))
            if actual_rates[-1] < 0.1:
                break

        for t in range(len(actual_rates) - 1, -1, -1):
            if t < 0:
                raise ValueError('t should never go below 0')
            if sum(actual_rates[t: max(len(actual_rates), t + stay_dur - 1)]) * voltage / 1000 / (
                    60 / period) >= requested_energy:
                return sum(actual_rates[:t]) * voltage / 1000 / (60 / period)
        return -1

    potential_caps = np.array([8, 24, 40, 60, 85, 100])
    for cap in potential_caps:
        if requested_energy > cap:
            continue
        init = _get_init_cap(requested_energy, stay_dur, cap, voltage, period)
        if init >= 0:
            return cap, init
    raise ValueError('No feasible battery size found.')

# def batt_cap_fn0(requested_energy, stay_dur, voltage, period):
#     def _get_init_cap(requested_energy, stay_dur, cap, voltage, period, max_rate=32, transition_soc=0.8):
#         delta_soc = requested_energy / cap
#         # Maximum rate of change of SoC in per period.
#         max_dsoc = max_rate * voltage / 1000 / cap / (60 / period)

#         # First, assume init_soc is after the transition_soc. In this
#         # case, the max init_soc has a closed form solution.
#         init_soc = 1 + delta_soc / (np.exp(max_dsoc * stay_dur / (transition_soc - 1)) - 1)
#         if init_soc >= transition_soc:
#             return init_soc

#         # If that didn't work, check that charging at max_dsoc for
#         # stay_dur periods yields greater than delta_soc SoC change.
#         if max_dsoc * stay_dur < delta_soc:
#             return -1
#         elif max_dsoc * stay_dur == delta_soc:
#             return transition_soc - delta_soc
#         # TODO: convergence of the lambertw function might be affected
#         # if max_dsoc * stay_dur - delta_soc is small. If this doesn't
#         # work, do the binary search method.

#         # Now return the max init_soc for which we can still deliver
#         # the required SoC.
#         init_soc = 1 \
#                    - delta_soc \
#                    - (transition_soc - 1) \
#                    * lambertw(-1 * np.exp(
#                         (max_dsoc * stay_dur - delta_soc + 1 - transition_soc) \
#                         / (transition_soc - 1)))
#         assert init_soc.real < transition_soc
#         assert init_soc.imag == 0
#         return init_soc.real * cap

#     potential_caps = np.array([8, 24, 40, 60, 85, 100])
#     for cap in potential_caps:
#         if requested_energy > cap:
#             continue
#         init = _get_init_cap(requested_energy, stay_dur, cap, voltage, period)
#         if init >= 0:
#             return cap, init
#     raise ValueError('No feasible battery size found.')


def batt_cap_fn(requested_energy, stay_dur, voltage, period):
    def _get_init_cap(requested_energy, stay_dur, cap, voltage, period, max_rate=32, transition_soc=0.8):
        delta_soc = requested_energy / cap
        # Maximum rate of change of SoC in per period.
        max_dsoc = max_rate * voltage / 1000 / cap / (60 / period)

        # First, assume init_soc is after the transition_soc. In this
        # case, the max init_soc has a closed form solution.
        init_soc = 1 + delta_soc / (np.exp(max_dsoc * stay_dur / (transition_soc - 1)) - 1)
        if init_soc >= transition_soc:
            return init_soc

        # If that didn't work, search over all possible init_soc for the
        # largest init_soc that still allows for delta_soc to be
        # delivered in stay_dur periods.
        def delta_soc_from_init_soc(init_soc):
            if stay_dur <= (transition_soc - init_soc) / max_dsoc:
                return max_dsoc * stay_dur
            return (
                1 \
                + np.exp((max_dsoc * stay_dur + init_soc - transition_soc) \
                    / (transition_soc - 1)) \
                * (transition_soc - 1) \
                - init_soc
            )
        # Before that, we make sure that starting at init_soc of 0, it's
        # possible to deliver the requested energy with this battery.
        if delta_soc_from_init_soc(0) < delta_soc:
            return -1

        # Since max energy delivered is decreasing in init_soc, we
        # use a binary search.
        def binsearch(f, lb, ub, targ, tol=1e-9):
            mid = (lb + ub) / 2
            val = f(mid)
            if abs(val - targ) < tol:
                return mid
            elif val - targ > 0:
                return binsearch(f, mid, ub, targ, tol=tol)
            else:
                return binsearch(f, lb, mid, targ, tol=tol)
        init_soc = binsearch(delta_soc_from_init_soc, 0, 1, delta_soc)
        assert init_soc < transition_soc
        return init_soc * cap

    potential_caps = np.array([8, 24, 40, 60, 85, 100])
    for cap in potential_caps:
        if requested_energy > cap:
            continue
        init = _get_init_cap(requested_energy, stay_dur, cap, voltage, period)
        if init >= 0:
            return cap, init
    raise ValueError('No feasible battery size found.')
