// TOGGLE SWITCH
// =============
// A simple boolean toggle switch that performs the same functionality as a
// checkbox.

"use strict";

var React = require("react");

var ToggleSwitch = React.createClass({

    propTypes: {
        toggled  : React.PropTypes.bool
      , onChange : React.PropTypes.func
    }

  , getDefaultProps: function() {
      return {
          toggled : false
        , onChange: function( toggleState, reactID ) {
                      console.warn("No onChange handler was provided for ToggleSwitch", reactID );
                    }
      };
    }

  , handleToggleClick: function( event, reactID ) {
      event.stopPropagation();
      event.preventDefault();

      this.props.onChange( !this.props.toggled, reactID );
    }

  , render: function() {
      var toggleClasses = ["toggle-switch"];

      if ( this.props.toggled ) {
        toggleClasses.push("on");
      }

      return (
        <div
          className = { toggleClasses.join(" ") }
          onClick   = { this.handleToggleClick } />
      );
    }

});

module.exports = ToggleSwitch;
