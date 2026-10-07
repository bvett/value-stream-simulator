from matplotlib import colormaps


class Viewer:
    """Defines the interface for simulation result viewers."""

    def __init__(self, colormap: str = "plasma"):
        self.colormap = colormaps[colormap]
