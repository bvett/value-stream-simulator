from matplotlib import colormaps


class Viewer:
    def __init__(self, colormap: str = 'plasma'):
        self.colormap = colormaps[colormap]

