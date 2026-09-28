from setuptools import find_packages, setup


PACKAGE_NAME = "kinesis_coordinator"


setup(
    name=PACKAGE_NAME,
    version="0.1.0",
    packages=find_packages(exclude=("test",)),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{PACKAGE_NAME}"]),
        (f"share/{PACKAGE_NAME}", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Kinesis maintainers",
    maintainer_email="maintainers@kinesis.invalid",
    description="ROS 2 adapter for deterministic Kinesis plans.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "coordinator = kinesis_coordinator.node:main",
        ],
    },
)
