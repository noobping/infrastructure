import * as Config from "resource:///org/gnome/shell/misc/config.js";
import { Extension } from "resource:///org/gnome/shell/extensions/extension.js";
import GLib from "gi://GLib";
import * as Main from "resource:///org/gnome/shell/ui/main.js";
import Shell from "gi://Shell";

export default class InPicture extends Extension {
  constructor(metadata) {
    super(metadata);
    this.windowCreatedSignal = null;
    this.settings = null;
  }

  enable() {
    this.settings = this.getSettings();
    this.windowCreatedSignal = global.display.connect(
      "window-created",
      (metaDisplay, metaWindow) => this.handleWindow(metaDisplay, metaWindow)
    );
    this.settings.set_string("gnome-version", Config.PACKAGE_VERSION);

    // Migrate from titles to identifiers
    const titles = this.settings.get_strv("titles");
    if (titles.length > 0) {
      let identifiers = [];
      for (const title of titles) {
        identifiers.push([title, ""]);
      }
      this.settings.set_value(
        "identifiers",
        new GLib.Variant("aas", identifiers)
      );
      this.settings.set_strv("titles", []);
    }
  }

  disable() {
    this.settings = null;
    if (this.windowCreatedSignal) {
      global.display.disconnect(this.windowCreatedSignal);
      this.windowCreatedSignal = null;
    }
  }

  handleWindow(metaDisplay, metaWindow) {
    metaWindow.previously_focused = metaDisplay.get_focus_window();

    const wrapper = metaWindow.get_compositor_private();
    const windowFirstSignal = wrapper.connect("first-frame", () => {
      this.moveResize(metaWindow);
      wrapper.disconnect(windowFirstSignal);
    });
  }

  async moveResize(metaWindow) {
    // Check if the window should be targeted
    const identifiers = this.settings.get_value("identifiers").deep_unpack();
    const windowTracker = Shell.WindowTracker.get_default();
    let matched = false;
    for (const pair of identifiers) {
      if (pair[0] !== "") {
        const title = metaWindow.get_title();
        if (!title) {
          continue;
        }
        if (
          !title
            .replace(/\u00A0/g, " ")
            .normalize("NFC")
            .includes(pair[0])
        ) {
          continue;
        }
      }
      if (pair[1] !== "") {
        const app = windowTracker.get_window_app(metaWindow).get_id();
        if (!app) {
          continue;
        }
        if (app !== pair[1]) {
          continue;
        }
      }
      matched = true;
      break;
    }
    if (!matched) return false;

    // If some other window was in focus, focus it again
    if (metaWindow.has_focus() && metaWindow.previously_focused) {
      Main.activateWindow(metaWindow.previously_focused);
    }

    // If the window was maximized, unmaximize it
    if (metaWindow.maximized_horizontally || metaWindow.maximized_vertically) {
      metaWindow.unmaximize(3);
      await new Promise((resolve) => {
        const sizeChangedSignal = metaWindow.connect("size-changed", () => {
          metaWindow.disconnect(sizeChangedSignal);
          resolve();
        });
      });
    }

    // Connect signal to move the window once resizing is finished
    const sizeChangedSignal = metaWindow.connect("size-changed", () => {
      metaWindow.disconnect(sizeChangedSignal);
      this.move(metaWindow);
    });

    // Get monitor work area
    const workspace = global.workspace_manager.get_active_workspace();
    const monitorIndex = metaWindow.get_monitor();
    const workArea = workspace.get_work_area_for_monitor(monitorIndex);

    // Calculate window dimensions
    const dimensions = this.calculateDimensions(workArea, metaWindow);

    // Calculate window position
    const position = this.calculatePosition(
      workArea,
      dimensions.width,
      dimensions.height
    );

    // Move and resize
    metaWindow.move_resize_frame(
      false,
      position.x,
      position.y,
      dimensions.width,
      dimensions.height
    );

    // Make window always above
    if (this.settings.get_boolean("top")) {
      metaWindow.make_above();
    }

    // Hide window from overviews
    if (this.settings.get_boolean("hide")) {
      metaWindow.hide_from_window_list();
    }

    // Show window on all workspaces
    if (this.settings.get_boolean("stick")) {
      metaWindow.stick();
    }

    return true;
  }

  move(metaWindow) {
    // Get monitor work area
    const workspace = global.workspace_manager.get_active_workspace();
    const monitorIndex = metaWindow.get_monitor();
    const workArea = workspace.get_work_area_for_monitor(monitorIndex);

    // Get current window dimensions
    const rectangle = metaWindow.get_frame_rect();

    // Calculate window position
    const position = this.calculatePosition(
      workArea,
      rectangle.width,
      rectangle.height
    );

    // Move
    metaWindow.move_frame(false, position.x, position.y);

    return true;
  }

  calculateDimensions(workArea, metaWindow) {
    const rectangle = metaWindow.get_frame_rect();
    const oldDiagonal = Math.sqrt(
      rectangle.width * rectangle.width + rectangle.height * rectangle.height
    );

    let newDiagonal;
    if (this.settings.get_boolean("use-relative")) {
      newDiagonal =
        (Math.sqrt(
          workArea.width * workArea.width + workArea.height * workArea.height
        ) *
          this.settings.get_int("diagonal-relative")) /
        100;
    } else {
      newDiagonal = this.settings.get_int("diagonal");
    }

    const coef = newDiagonal / oldDiagonal;
    const width = Math.ceil(rectangle.width * coef);
    const height = Math.ceil(rectangle.height * coef);

    return {
      width: width,
      height: height,
    };
  }

  calculatePosition(workArea, width, height) {
    const corner = this.settings.get_int("corner");
    const marginX = this.settings.get_int("margin-x");
    const marginY = this.settings.get_int("margin-y");
    let x, y;
    switch (corner) {
      case 0:
        x = workArea.x + marginX;
        y = workArea.y + marginY;
        break;
      case 1:
        x = workArea.x + workArea.width - width - marginX;
        y = workArea.y + marginY;
        break;
      case 2:
        x = workArea.x + marginX;
        y = workArea.y + workArea.height - height - marginY;
        break;
      default:
        x = workArea.x + workArea.width - width - marginX;
        y = workArea.y + workArea.height - height - marginY;
        break;
    }
    return {
      x: x,
      y: y,
    };
  }
}
