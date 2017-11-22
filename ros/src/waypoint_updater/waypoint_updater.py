#!/usr/bin/env python

# Global packages
import math
import numpy as np
import rospy
import scipy.spatial
import time
import yaml

# Local project packages
import waypoint_lib.helper as helper
from geometry_msgs.msg import PoseStamped
from geometry_msgs.msg import TwistStamped

from std_msgs.msg import Int32
from geometry_msgs.msg import PoseStamped
from styx_msgs.msg import Lane, Waypoint
from styx_msgs.msg import TrafficLightArray, TrafficLight


'''
This node will publish waypoints from the car's current position to some `x` distance ahead.

As mentioned in the doc, you should ideally first implement a version which does not care
about traffic lights or obstacles.

Once you have created dbw_node, you will update this node to use the status of traffic lights too.

Please note that our simulator also provides the exact location of traffic lights and their
current status in `/vehicle/traffic_lights` message. You can use this message to build this node
as well as to verify your TL classifier.

TODO (for Yousuf and Aaron): Stopline location for each traffic light.
'''

LOOKAHEAD_WPS = 200 # Number of waypoints we will publish. You can change this number


class WaypointUpdater(object):
    def __init__(self):
        rospy.init_node('waypoint_updater')

        rospy.Subscriber('/current_pose', PoseStamped, self.pose_cb)
        rospy.Subscriber('/base_waypoints', Lane, self.waypoints_cb)

        # TODO: Add a subscriber for /traffic_waypoint and /obstacle_waypoint below
        rospy.Subscriber('/traffic_waypoint', TrafficLight, self.upcoming_traffic_light_cb)
        rospy.Subscriber('/current_velocity', TwistStamped, self.current_velocity_cb, queue_size=1)

        config_string = rospy.get_param("/traffic_light_config")
        self.config = yaml.load(config_string)
        self.initialize_stop_line_positions_kdtree()

        self.final_waypoints_pub = rospy.Publisher('final_waypoints', Lane, queue_size=1)
        self.stop_line_waypoint_pub = rospy.Publisher('stop_line_waypoint', Int32, queue_size=1)

        # TODO: Add other member variables you need below
        # A list of all the waypoints of the track as reported by master node.
        self.waypoints = None
        self.current_velocity = 0.0

        self.waypoints_kdtree = None
        self.current_traffic_light = None

        self.current_pose = None

        rospy.spin()

    def initialize_stop_line_positions_kdtree(self):
        self.stop_line_positions = self.config['stop_line_positions']
        self.stop_line_positions_kdtree = scipy.spatial.cKDTree(self.stop_line_positions)

    def current_velocity_cb(self, curr_vel_msg):
        self.current_velocity = curr_vel_msg.twist.linear.x

    def set_velocity_leading_to_stop_point(self, current_pose_wp_idx, stop_point_idx):
        new_waypoints = self.waypoints[:]  # Copy the list

        # Compute the total distances leading up to the stop point
        distances = [self.distance(new_waypoints, i, i+1)
                     for i in range(current_pose_wp_idx, stop_point_idx + 1)]

        total_distance = int(math.floor(sum(distances)))

        VEL_THRESHOLD = 5
        # if the deceleration < VEL_THRESHOLD mph then increase the speed to a proportion of the distance
        if self.current_velocity < VEL_THRESHOLD:
            # Use a gaussian distribution to get the car to speed up.
            # x = np.linspace(0, total_distance, total_distance)
            # mu, sig = 0.1, 1.0
            # distribution = np.exp(-np.power(x - mu, 2.) / (2 * np.power(sig, 2.)))
            distribution = np.concatenate((
                np.linspace(self.current_velocity, VEL_THRESHOLD, total_distance),
                np.linspace(VEL_THRESHOLD, 0, total_distance)), axis=0)
        else:
            # Use a linear distribution to get the speeds.
            distribution = np.linspace(self.current_velocity, 0.0, total_distance, endpoint=True)

        dist_idx = 0
        velocities = []
        for wp_idx in range(current_pose_wp_idx + 1, stop_point_idx + 1):
            velocity = distribution[int(distances[dist_idx])]
            velocities.append(velocity)
            self.set_waypoint_velocity(new_waypoints, wp_idx, velocity)
            dist_idx += 1

        return new_waypoints

    def pose_cb(self, pose):
        if self.waypoints is None:
            rospy.error('No base_waypoints have been received by master')
            return

        self.current_pose = pose

        # Compute the index of the waypoint closest to the current pose.
        closest_wp_idx = helper.next_waypoint_index_kdtree(self.current_pose.pose, self.waypoints_kdtree)

        # Find the closest stop line position if we have to stop the car.
        _, stop_line_idx = self.stop_line_positions_kdtree.query([pose.pose.position.x, pose.pose.position.y])
        stop_line_positions = self.stop_line_positions[stop_line_idx]

        # Find the closest waypoint index for the stop line position
        stop_line_pose = PoseStamped()
        stop_line_pose.pose.position.x = stop_line_positions[0]
        stop_line_pose.pose.position.y = stop_line_positions[1]
        stop_line_pose.pose.orientation = pose.pose.orientation
        stop_line_waypoint_idx = helper.next_waypoint_index_kdtree(stop_line_pose.pose, self.waypoints_kdtree)

        self.stop_line_waypoint_pub.publish(Int32(stop_line_waypoint_idx))

        # If the light is RED or YELLOW then slowly decrease the speed.
        if self.current_traffic_light is not None and\
           (self.current_traffic_light.state == 0 or self.current_traffic_light.state == 1):
            new_waypoints = self.set_velocity_leading_to_stop_point(closest_wp_idx, stop_line_waypoint_idx)
        else:
            # If the lights are green just continue on the same path.
            new_waypoints = self.waypoints

        # Find number of waypoints ahead dictated by LOOKAHEAD_WPS
        next_wps = new_waypoints[closest_wp_idx:closest_wp_idx + LOOKAHEAD_WPS]
        self.current_traffic_light = None
        self.publish(next_wps)

    def waypoints_cb(self, waypoints):
        rospy.loginfo('Received Base waypoints from master...')
        self.waypoints = waypoints.waypoints
        # Create a numpy version of the waypoints
        np_waypoints = helper.create_numpy_repr(self.waypoints)
        self.waypoints_kdtree = scipy.spatial.cKDTree(np_waypoints, leafsize=5)
        rospy.loginfo('Created KDTree for vehicle waypoints for fast NN query')

    def upcoming_traffic_light_cb(self, msg):
        # rospy.loginfo('Received traffic light color callback')
        self.current_traffic_light = msg

    def obstacle_cb(self, msg):
        # TODO: Callback for /obstacle_waypoint message. We will implement it later
        pass

    def get_waypoint_velocity(self, waypoint):
        return waypoint.twist.twist.linear.x

    def set_waypoint_velocity(self, waypoints, waypoint, velocity):
        waypoints[waypoint].twist.twist.linear.x = velocity

    def distance(self, waypoints, wp1, wp2):
        dist = 0
        dl = lambda a, b: math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2 + (a.z-b.z)**2)
        for i in range(wp1, wp2+1):
            dist += dl(waypoints[wp1].pose.pose.position, waypoints[i].pose.pose.position)
            wp1 = i
        return dist

    def publish(self, waypoints):
        lane = Lane()
        lane.header.frame_id = '/world'
        lane.header.stamp = rospy.Time(time.time())
        lane.waypoints = waypoints
        self.final_waypoints_pub.publish(lane)


if __name__ == '__main__':
    try:
        WaypointUpdater()
    except rospy.ROSInterruptException:
        rospy.logerr('Could not start waypoint updater node.')
