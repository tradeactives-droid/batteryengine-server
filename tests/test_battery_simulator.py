def simulate_with_battery(self) -> SimulationResult:
        """
        Correcte batterijsimulatie:
        - Laadt bij overschot (PV > load)
        - Ontlaadt bij tekort (load > PV)
        - Respecteert P_max, E_min, E_max, efficiënties
        """

        load = self.load.values
        pv = self.pv.values
        n = len(load)

        dt = self.load.dt_hours
        batt = self.battery

        # Batterijparameters
        soc = batt.initial_soc_kwh
        E_min = batt.E_min
        E_max = batt.E_max
        P_max = batt.P_max
        eta_c = batt.eta_c
        eta_d = batt.eta_d

        import_profile = []
        export_profile = []
        soc_profile = []

        for t in range(n):
            net = load[t] - pv[t]  # positief = tekort, negatief = overschot

            # ------------------------------------------
            # 1) TEKORT → ONTLADEN
            # ------------------------------------------
            if net > 0:
                needed = net  # kWh
                max_discharge = P_max * dt  # kWh uit batterij-vermogen

                # maximale energie die batterij kan afgeven (inclusief efficiëntie)
                deliverable = max_discharge * eta_d

                delivered = min(needed, deliverable)

                # vanwege efficiëntie moet batterij MEER energie verliezen dan afgeleverd
                batt_energy_used = delivered / eta_d

                # Limiet: soc mag niet onder E_min komen
                if soc - batt_energy_used < E_min:
                    batt_energy_used = soc - E_min
                    delivered = batt_energy_used * eta_d

                soc -= batt_energy_used

                grid_import = needed - delivered
                if grid_import < 0:
                    grid_import = 0

                import_profile.append(grid_import)
                export_profile.append(0.0)

            # ------------------------------------------
            # 2) OVERSCHOT → LADEN
            # ------------------------------------------
            else:
                surplus = -net
                max_charge = P_max * dt

                charge_input = min(surplus, max_charge)  # energie die je erin stopt
                charge_stored = charge_input * eta_c      # SoC stijgt minder door verlies

                # Limiet: soc mag niet boven E_max komen
                if soc + charge_stored > E_max:
                    charge_stored = E_max - soc
                    charge_input = charge_stored / eta_c

                soc += charge_stored

                # export is overschot dat niet geladen kan worden
                grid_export = surplus - charge_input
                if grid_export < 0:
                    grid_export = 0.0

                import_profile.append(0.0)
                export_profile.append(grid_export)

            soc_profile.append(soc)

        return SimulationResult(
            import_kwh=sum(import_profile),
            export_kwh=sum(export_profile),
            import_profile=import_profile,
            export_profile=export_profile,
            soc_profile=soc_profile,
            dt_hours=dt
        )
