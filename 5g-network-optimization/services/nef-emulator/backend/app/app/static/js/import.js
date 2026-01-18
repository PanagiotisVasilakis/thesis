// ===============================================
//               Global variables
// ===============================================
var cm = null;  // codemirror
var scenario_json_str = "";




// ===============================================
//                 Document ready
// ===============================================
$(document).ready(function () {

  cm = CodeMirror.fromTextArea(document.getElementById("import_text_area"),
    {
      lineNumbers: true,
      mode: "javascript"
    }
  );

  $(".CodeMirror").css("font-size", 11);
  // cm.refresh();



  $('#import-btn-save').on('click', function () {
    // check textarea is empty
    scenario_json_str = cm.getValue();

    if (scenario_json_str.length == 0) {
      ui_display_toast_msg("warning", "Oups!", "Make sure you add some json first!");
    }
    else {
      api_import_scenario(scenario_json_str);
    }
  });

});



function api_import_scenario(data_json_str) {

  var url = app.api_url + '/utils/import/scenario';

  $.ajax({
    type: 'POST',
    url: url,
    contentType: 'application/json',
    headers: {
      "authorization": "Bearer " + app.auth_obj.access_token
    },
    data: data_json_str,
    processData: false,
    beforeSend: function () {
      //
    },
    success: function (data) {
      ui_display_toast_msg("success", "Finished!", "Successfully imported the scenario.");
    },
    error: function (err) {
      console.log(err);
      ui_display_toast_msg("error", "Oups!", "The scenario could not be imported.");
    },
    complete: function () {
      //
    },
    timeout: 30000
  });
}




function ui_display_toast_msg(type, title, text) {
  toastr_options = {
    closeButton: true,
    positionClass: "toast-bottom-right",
    // timeOut         : 0,
    // extendedTimeOut : 0
  };
  toastr[type](text, title, toastr_options);
}


// ===============================================
//        Pre-built Scenario Loader
// ===============================================

function loadPrebuiltScenario() {
  var scenarioName = $('#scenario-select').val();

  if (!scenarioName) {
    ui_display_toast_msg("warning", "Select Scenario", "Please select a scenario from the dropdown first.");
    return;
  }

  var scenarioUrl = '/static/scenarios/' + scenarioName + '.json';

  $.ajax({
    type: 'GET',
    url: scenarioUrl,
    dataType: 'json',
    beforeSend: function () {
      $('#load-scenario-btn').prop('disabled', true).html('Loading...');
    },
    success: function (data) {
      // Pretty print the JSON in the editor
      var jsonStr = JSON.stringify(data, null, 2);
      cm.setValue(jsonStr);
      ui_display_toast_msg("success", "Loaded!", "Scenario '" + scenarioName + "' loaded. Click Import to apply.");
    },
    error: function (err) {
      console.log(err);
      ui_display_toast_msg("error", "Error", "Could not load scenario: " + scenarioName);
    },
    complete: function () {
      $('#load-scenario-btn').prop('disabled', false).html('<svg class="icon"><use xlink:href="static/vendors/@coreui/icons/svg/free.svg#cil-cloud-download"></use></svg> Load Scenario');
    }
  });
}
