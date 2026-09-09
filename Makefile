.PHONY: test test-assets test-distributed simulate simulate-large compare trials build-ros test-ros docker-build docker-run

test: test-assets
	cd simulator && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m pytest -p no:cacheprovider

test-assets:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s simulation/tests -v

test-distributed:
	cd simulator && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m pytest -p no:cacheprovider tests/test_distributed_runtime.py

simulate:
	cd simulator && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m swarmroute simulate scenarios/warehouse-12.json --max-ticks 180

simulate-large:
	cd simulator && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m swarmroute simulate scenarios/fulfillment-large-12.json --max-ticks 360 --tick-seconds 5

compare:
	cd simulator && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m swarmroute compare scenarios/warehouse-12.json --max-ticks 180

trials:
	cd simulator && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m swarmroute trials scenarios/warehouse-12.json --trials 30 --max-ticks 180

build-ros:
	simulation/scripts/build_ros.sh

test-ros: build-ros
	cd simulation/ros2_ws && colcon test --event-handlers console_direct+ && colcon test-result --verbose

docker-build:
	docker compose -f simulation/docker-compose.yml build

docker-run:
	docker compose -f simulation/docker-compose.yml up --abort-on-container-exit
