from simpy import Environment


class Epoch:
    def __init__(self, env: Environment):
        self._offset_t: float = env.now

    def to_sim_time(self, epoch_t: float):
        if epoch_t < 0:
            raise ValueError("epoch time must be >= 0")

        return epoch_t + self._offset_t

    def to_epoch_time(self, sim_t: float):
        if sim_t < self._offset_t:
            raise ValueError("time cannot be prior to beginning of epoch")

        return sim_t - self._offset_t
