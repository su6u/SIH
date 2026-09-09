from setuptools import find_packages, setup


PACKAGE_NAME = "swarmroute_peer"


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
    maintainer="SwarmRoute maintainers",
    maintainer_email="swarmroute@invalid.example",
    description="One distributed ROS 2 peer for a single SwarmRoute AMR.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "peer_node = swarmroute_peer.peer_node:main",
        ],
    },
)
