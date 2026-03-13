# Value Stream Simulator

## What Problem is Being Solved?
Organizations that invest in CI/CD automation may still experience customers that are negatively impacted by delivery pace and/or quality, which can lead to chasing metrics such as release frequency and test coverage.  Doing so can be counterproductive without understanding the *value stream* of software delivery.

A proposed feature or change has an associated value, often implicitly derived from an expected customer benefit.  The value begins to depreciate immediately, and continues to depreciate until it is delivered into production.  This _loss_ represents the cost of delay.

Given a set of proposed features, hereafter referred to as _tasks_, value is maximized when the highest-valued tasks are delivered into production in the least amount of time.  While conceptually simple, optimization requires an understanding of the impact technical and organizational factors have on shipping software.

Understanding where delays and disruptions occur and their impact can help organizations prioritize improvements.   

## Getting Started
### Environment
1. Python >= 3.9 is required 
2. Clone this repository and cd to its root
```shell
git clone https://github.com/bvett/value-stream-simulator.git
cd value-stream-simulator
```

3. Create and load a virtual environment:
  * Linux/Mac:
```shell
python -m venv .venv
source .venv/bin/activate
```
  * Windows:
```shell
python -m venv venv
venv/Scripts/activate
```
4. Install Dependencies
```shell
pip install -r requirements.txt
```

5. Install project as a local dependency
```shell
pip install -e .
```
### Demo
[examples/demo.py](https://github.com/bvett/value-stream-simulator/blob/main/src/examples/demo.py) runs a sample simulation then presents the results as different plots

```shell
python src/examples/demo.py
```

### Tutorial
[src/examples/tutorial.ipynb](https://github.com/bvett/value-stream-simulator/blob/main/src/examples/tutorial.ipynb) presents a more detailed walkthrough as a Jupyter notebook.

## Project Status and Objectives
This project provides a limited feature set that supports correlating delivery cadence and development team size/ability against value & loss.  Near-term objectives include:

* Introducing additional simulation parameters, including:
  * stability, including maturity of monitoring, observability, and runbook automation
  * task-interdependencies
  * developer turnover/onboarding
  * testing effectiveness
  * requirements/priority stability
  * impact of 'mandatory work' 
* Introduce notion of cost and enable value stream to be optimized while minimizing cost
* Enabling simulations to cover additional dimensions, including feedback on factors that introduce the greatest loss

Future objectives:
* Web service/UI to offer more dynamic 'what-if' analysis
* Extensibility
* Data source integration







