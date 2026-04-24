import Adw from "gi://Adw";
import Gio from "gi://Gio";
import Gtk from "gi://Gtk";
import GLib from "gi://GLib";
import {
  ExtensionPreferences,
  gettext as _,
} from "resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js";

export default class InPicturePreferences extends ExtensionPreferences {
  fillPreferencesWindow(window) {
    const settings = this.getSettings();

    window.search_enabled = true;

    const builder = new Gtk.Builder();
    builder.set_translation_domain(this.uuid);
    builder.add_from_file(this.path + "/ui/prefs.ui");

    const page = builder.get_object("preferences_page");
    window.add(page);

    /* Position */
    const cornerRow = builder.get_object("corner_row");
    cornerRow.selected = settings.get_int("corner");
    cornerRow.connect("notify::selected", () => {
      settings.set_int("corner", cornerRow.get_selected());
    });

    const marginXAdjustment = builder.get_object("margin_x_adjustment");
    marginXAdjustment.value = settings.get_int("margin-x");
    marginXAdjustment.connect("value-changed", () => {
      settings.set_int("margin-x", marginXAdjustment.get_value());
    });

    const marginYAdjustment = builder.get_object("margin_y_adjustment");
    marginYAdjustment.value = settings.get_int("margin-y");
    marginYAdjustment.connect("value-changed", () => {
      settings.set_int("margin-y", marginYAdjustment.get_value());
    });

    /* Diagonal */
    const diagonalAdjustment = builder.get_object("diagonal_adjustment");
    diagonalAdjustment.connect("value-changed", () => {
      const useRelative = settings.get_boolean("use-relative");
      if (useRelative) {
        settings.set_int("diagonal-relative", diagonalAdjustment.get_value());
      } else {
        settings.set_int("diagonal", diagonalAdjustment.get_value());
      }
    });

    const diagonalUnits = builder.get_object("diagonal_units");
    diagonalUnits.connect("notify::selected", () => {
      settings.set_boolean("use-relative", diagonalUnits.get_selected() === 0);
      diagonalAdjustmentUpdate();
    });

    diagonalAdjustmentUpdate();

    function diagonalAdjustmentUpdate() {
      const useRelative = settings.get_boolean("use-relative");
      if (useRelative) {
        diagonalAdjustment.lower = 5;
        diagonalAdjustment.upper = 100;
        diagonalAdjustment.step_increment = 5;
        diagonalAdjustment.page_increment = 20;
        diagonalAdjustment.value = settings.get_int("diagonal-relative");
        diagonalUnits.set_selected(0);
      } else {
        diagonalAdjustment.lower = 100;
        diagonalAdjustment.upper = 1500;
        diagonalAdjustment.step_increment = 10;
        diagonalAdjustment.page_increment = 100;
        diagonalAdjustment.value = settings.get_int("diagonal");
        diagonalUnits.set_selected(1);
      }
    }

    /* Visibility */
    const stayOnTopRow = builder.get_object("stay_on_top_row");
    settings.bind("top", stayOnTopRow, "active", Gio.SettingsBindFlags.DEFAULT);

    const stickRow = builder.get_object("stick_row");
    settings.bind("stick", stickRow, "active", Gio.SettingsBindFlags.DEFAULT);

    const hideFromWindowList = builder.get_object("hide_from_window_list_row");
    const gnomeVersion = settings.get_string("gnome-version");
    if (Number(gnomeVersion.split(".")[0]) < 49) {
      builder.get_object("visibility_group").remove(hideFromWindowList);
    }
    settings.bind(
      "hide",
      hideFromWindowList,
      "active",
      Gio.SettingsBindFlags.DEFAULT,
    );

    /* Identifiers */
    const identifiersAdd = builder.get_object("identifiers_add");
    identifiersAdd.connect("clicked", () => identifiersDialog.present(page));

    const identifiersDialog = builder.get_object("identifiers_dialog");
    identifiersDialog.add_response("close", _("Close"));
    identifiersDialog.add_response("add", _("Add"));
    identifiersDialog.set_response_appearance(
      "add",
      Adw.ResponseAppearance.SUGGESTED,
    );

    const identifierTitleRow = builder.get_object("identifier_title_row");
    identifierTitleRow.connect("entry-activated", () => {
      identifiersListSave(
        identifiersDialog,
        "add",
        identifierTitleRow,
        identifierAppRow,
      );
    });

    const identifierAppRow = builder.get_object("identifier_app_row");
    identifierAppRow.connect("entry-activated", () => {
      identifiersListSave(
        identifiersDialog,
        "add",
        identifierTitleRow,
        identifierAppRow,
      );
    });

    identifiersDialog.connect("response", (dialog, response) => {
      identifiersListSave(
        dialog,
        response,
        identifierTitleRow,
        identifierAppRow,
      );
    });
    identifiersDialog.connect("map", () => {
      identifierTitleRow.grab_focus();
    });

    const identifiersList = builder.get_object("identifiers_list");
    identifiersListPopulate();

    function identifiersListPopulate() {
      identifiersList.remove_all();

      const identifiers = settings.get_value("identifiers").deep_unpack();
      for (const pair of identifiers) {
        const identifierRow = new Adw.ActionRow({
          title:
            pair[0] +
            (pair[0] && pair[1] ? " • " : "") +
            "<i>" +
            pair[1] +
            "</i>",
          selectable: false,
          activatable: true,
        });
        identifiersList.append(identifierRow);

        const deleteButton = new Gtk.Button({
          icon_name: "user-trash-symbolic",
          valign: Gtk.Align.CENTER,
        });
        identifierRow.add_suffix(deleteButton);
        deleteButton.add_css_class("circular");
        deleteButton.add_css_class("flat");
        deleteButton.connect("clicked", () => {
          settings.set_value(
            "identifiers",
            new GLib.Variant(
              "aas",
              identifiers.filter(
                (p) => !(p[0] === pair[0] && p[1] === pair[1]),
              ),
            ),
          );
          identifiersListPopulate();
        });
      }
    }

    function identifiersListSave(dialog, response, titleEntry, appEntry) {
      if (response === "add") {
        const title = titleEntry.text.trim();
        const app = appEntry.text.trim();
        titleEntry.text = "";
        appEntry.text = "";

        if (title.length + app.length === 0) {
          const identifierWarning = builder.get_object("identifier_warning");
          window.add_toast(identifierWarning);
        } else {
          const identifiers = settings.get_value("identifiers").deep_unpack();
          let duplicate = false;
          for (const pair of identifiers) {
            if (pair[0] === title && pair[1] === app) {
              duplicate = true;
            }
          }
          if (!duplicate) {
            identifiers.push([title, app]);
            settings.set_value(
              "identifiers",
              new GLib.Variant("aas", identifiers),
            );
            identifiersListPopulate();
          }
        }
      }

      dialog.close();
    }
  }
}
