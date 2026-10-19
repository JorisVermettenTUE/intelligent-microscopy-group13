// ============================================================
// XY GANTRY - CONTROLLED FROM PYTHON
//
// Python stuurt:
// X,1000
// X,-1000
// Y,500
// Y,-500
//
// Arduino antwoordt met DONE wanneer beweging klaar is.
// ============================================================


// ------------------------------------------------------------
// PINS
// ------------------------------------------------------------

const int stepMotor1 = 2;
const int dirMotor1  = 5;

const int stepMotor2 = 3;
const int dirMotor2  = 6;

const int safetyPin = 8;


// ------------------------------------------------------------
// SNELHEID
//
// hoger = langzamer
// lager = sneller
// ------------------------------------------------------------

const int stepDelay = 600;


// ------------------------------------------------------------
// DRIVERS UIT IN STILSTAND
//
// true  = drivers alleen aan tijdens bewegen (geen trillen/zoemen)
// false = drivers altijd aan (meer houdkracht)
// ------------------------------------------------------------

const bool disableWhenIdle = true;


// ============================================================
// SETUP
// ============================================================

void setup() {

  pinMode(stepMotor1, OUTPUT);
  pinMode(dirMotor1, OUTPUT);

  pinMode(stepMotor2, OUTPUT);
  pinMode(dirMotor2, OUTPUT);

  pinMode(safetyPin, OUTPUT);

  // Motor drivers: uit tot er bewogen wordt (of altijd aan)
  digitalWrite(safetyPin, disableWhenIdle ? HIGH : LOW);

  Serial.begin(115200);

  Serial.println("READY");
}


// ============================================================
// BEIDE MOTOREN ÉÉN STAP
// ============================================================

void stepBoth(long numberOfSteps) {

  // Drivers aan (LOW = aan) en even laten opstarten
  digitalWrite(safetyPin, LOW);
  delay(2);

  for (long i = 0; i < numberOfSteps; i++) {

    digitalWrite(stepMotor1, HIGH);
    digitalWrite(stepMotor2, HIGH);

    delayMicroseconds(stepDelay);

    digitalWrite(stepMotor1, LOW);
    digitalWrite(stepMotor2, LOW);

    delayMicroseconds(stepDelay);
  }

  if (disableWhenIdle) {

    // Kort laten uitdempen voordat de stroom eraf gaat
    delay(50);

    digitalWrite(safetyPin, HIGH);
  }
}


// ============================================================
// X-BEWEGING
//
// positief = rechts
// negatief = links
// ============================================================

void moveX(long steps) {

  if (steps == 0) {
    return;
  }

  if (steps > 0) {

    // Rechts
    digitalWrite(dirMotor1, HIGH);
    digitalWrite(dirMotor2, HIGH);

  } else {

    // Links
    digitalWrite(dirMotor1, LOW);
    digitalWrite(dirMotor2, LOW);

    steps = -steps;
  }

  stepBoth(steps);
}


// ============================================================
// Y-BEWEGING
//
// positief = vooruit
// negatief = achteruit
// ============================================================

void moveY(long steps) {

  if (steps == 0) {
    return;
  }

  if (steps > 0) {

    // Vooruit
    digitalWrite(dirMotor1, HIGH);
    digitalWrite(dirMotor2, LOW);

  } else {

    // Achteruit
    digitalWrite(dirMotor1, LOW);
    digitalWrite(dirMotor2, HIGH);

    steps = -steps;
  }

  stepBoth(steps);
}


// ============================================================
// COMMANDO UITVOEREN
// ============================================================

void executeCommand(String command) {

  command.trim();

  if (command.length() < 3) {
    return;
  }

  char axis = command.charAt(0);

  int commaPosition = command.indexOf(',');

  if (commaPosition == -1) {
    return;
  }

  long steps =
    command.substring(commaPosition + 1).toInt();


  if (axis == 'X') {

    moveX(steps);

    Serial.println("DONE");

  }

  else if (axis == 'Y') {

    moveY(steps);

    Serial.println("DONE");

  }
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  if (Serial.available() > 0) {

    String command =
      Serial.readStringUntil('\n');

    executeCommand(command);
  }
}